#!/usr/bin/env python3
"""Life Director maintenance: stdlib only; no model, network, deletion or background job."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import posixpath
import re
import zipfile

NAME = 'life-director'
FILES = ('SKILL.md', 'agents/openai.yaml', 'references/naval.md', 'references/jung.md',
         'references/munger.md', 'references/musk.md', 'references/decision-card.md',
         'references/follow-up.md', 'references/evolution.md', 'evals/cases.json',
         'evals/rubric.md', 'scripts/maintain.py', 'version.json', 'CHANGELOG.md')
PATCH_FILES = {'SKILL.md', 'agents/openai.yaml', 'version.json', 'CHANGELOG.md', 'evals/cases.json'}
LIMIT = 20 * 1024 * 1024

def require(ok, message):
    if not ok:
        raise ValueError(message)

def no_links(path):
    p = Path(path).absolute()
    require(not any(x.is_symlink() for x in (p, *p.parents)), '拒绝符号链接路径: ' + str(p))
    return p

def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())

def read_json(path):
    return json.loads(no_links(path).read_text(encoding='utf-8'))

def sha(data):
    return hashlib.sha256(data).hexdigest()

def fingerprint(blobs):
    return sha(b''.join(k.encode() + b'\0' + sha(blobs[k]).encode() + b'\n' for k in sorted(blobs)))

def validate(blobs):
    require(set(blobs) == set(FILES), '运行文件集不完整或含未授权文件')
    t = {k: v.decode('utf-8') for k, v in blobs.items()}
    entry = t['SKILL.md']
    require(entry.startswith('---\n') and entry.count('---\n') >= 2, '缺少 frontmatter')
    front = entry.split('---\n', 2)[1]
    require(re.search(r'^name: life-director\s*$', front, re.M), '名称不匹配')
    require(re.search(r'^description: .+', front, re.M), '缺少 description')
    require('[TODO:' not in entry, '未完成占位符')
    for name, text in t.items():
        if name.endswith('.md'):
            for target in re.findall(r'\]\(([^\s)]+)\)', text):
                if not target.startswith(('https://', 'http://', '#')):
                    link = posixpath.normpath(str(Path(name).parent / target.split('#')[0]))
                    require(link in FILES, '失效或越界链接: ' + name + ' -> ' + target)
    version = json.loads(t['version.json'])
    require(version.get('name') == NAME, '版本名称不匹配')
    require(re.fullmatch(r'\d+\.\d+\.\d+', version.get('version', '')), '版本格式错误')
    require('## ' + version['version'] + ' — ' in t['CHANGELOG.md'], '版本未记入 CHANGELOG')
    cases = json.loads(t['evals/cases.json'])
    require(cases.get('fictional') is True and cases.get('schema_version') == 1, '案例必须是虚构的')
    ids = set()
    for c in cases.get('cases', []):
        require(re.fullmatch(r'[a-z][a-z0-9_]*', c.get('id', '')) and c['id'] not in ids, '案例 ID 错误')
        ids.add(c['id'])
        for key in ('user_turns', 'expectations', 'forbidden'):
            require(isinstance(c.get(key), list) and c[key] and
                    all(isinstance(x, str) and x.strip() for x in c[key]), '案例字段错误: ' + key)
    require(ids, '案例为空')
    compile(t['scripts/maintain.py'], 'maintain.py', 'exec')
    return dict(name=NAME, version=version['version'], sha256=fingerprint(blobs),
                files=len(blobs), cases=len(ids), behavior_test='not_run_by_this_command')

def inventory(root):
    root = no_links(root)
    blobs = {}
    for name in FILES:
        p = no_links(root / name)
        require(p.is_file() and p.stat().st_size <= LIMIT, '运行文件缺失或过大: ' + name)
        blobs[name] = p.read_bytes()
    validate(blobs)
    return blobs

def state_path(root, value):
    if not value:
        require(root.parent.name == 'skills' and root.parent.parent.name == '_agent',
                '其他环境必须显式指定 --state-root')
        value = root.parent.parent / 'tools' / NAME
    state = no_links(value)
    require(not inside(state, root) and not inside(root, state), '源与维护目录不能包含彼此')
    return state

def init_state(state):
    for name in ('candidates', 'evaluations', 'versions'):
        no_links(state / name).mkdir(parents=True, exist_ok=True)
    no_links(state / 'feedback.jsonl').touch(exist_ok=True)

@contextmanager
def locked(state):
    import fcntl
    init_state(state)
    with no_links(state / 'operation.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
        fcntl.flock(f, fcntl.LOCK_UN)

def write(path, data):
    p = no_links(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)

def archive_write(path, entries):
    p = no_links(path)
    require(not p.exists(), '拒绝覆盖已有快照: ' + str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, entries[name])

def archive_read(path, expected):
    with zipfile.ZipFile(no_links(path)) as z:
        items = z.infolist()
        require(len(items) == len(expected) and {i.filename for i in items} == set(expected),
                '归档文件集异常，可能含私有资料、重复项或越界文件')
        require(sum(i.file_size for i in items) <= LIMIT, '归档过大')
        require(all(not i.is_dir() and (i.external_attr >> 16) & 0o170000 != 0o120000 for i in items),
                '归档含符号链接或目录项')
        return {i.filename: z.read(i) for i in items}

def read_snapshot(path):
    data = archive_read(path, ['manifest.json', *('payload/' + k for k in FILES)])
    m = json.loads(data.pop('manifest.json'))
    blobs = {k.removeprefix('payload/'): v for k, v in data.items()}
    info = validate(blobs)
    require(m.get('files') == {k: sha(v) for k, v in blobs.items()} and
            m.get('sha256') == info['sha256'] and m.get('version') == info['version'], '快照完整性错误')
    return blobs

def snapshot(blobs, state):
    info = validate(blobs)
    p = state / 'versions' / (info['version'] + '-' + info['sha256'][:16] + '.zip')
    m = dict(version=info['version'], sha256=info['sha256'], files={k: sha(v) for k, v in blobs.items()})
    if p.exists():
        require(read_snapshot(p) == blobs, '同名快照冲突')
    else:
        archive_write(p, dict({'payload/' + k: v for k, v in blobs.items()},
                             **{'manifest.json': json.dumps(m, ensure_ascii=False, indent=2).encode()}))
    return p

def package(blobs, root, output, state=None):
    output = no_links(output)
    require(not inside(output, root), '安装包不能写入源目录')
    entries = {NAME + '/' + k: v for k, v in blobs.items()}
    if output.exists():
        previous = archive_read(output, entries)
        validate({k.removeprefix(NAME + '/'): v for k, v in previous.items()})
        backup_dir = state / 'versions' if state else output.parent
        backup = no_links(backup_dir / ('life-director-package-' + sha(output.read_bytes())[:16] + '.skill'))
        require(backup != output, '安装包输出路径不能与旧包备份路径相同')
        if not backup.exists():
            write(backup, output.read_bytes())
        else:
            require(backup.read_bytes() == output.read_bytes(), '安装包备份冲突')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = no_links(output.parent / (output.name + '.' + fingerprint(blobs)[:16] + '.staged'))
    if staging.exists():
        require(archive_read(staging, entries) == entries, '已有打包暂存文件冲突')
    else:
        archive_write(staging, entries)
    require(archive_read(staging, entries) == entries, '打包字节核对失败')
    staging.replace(output)
    return output

def cases(blobs):
    return {c['id']: c for c in json.loads(blobs['evals/cases.json'])['cases']}

def gate(root, candidate, report_path, state, approval_path=None):
    before, after = inventory(root), inventory(candidate)
    report = read_json(report_path)
    require(report.get('baseline_sha256') == fingerprint(before) and
            report.get('candidate_sha256') == fingerprint(after), '评估报告指纹过期或不匹配')
    require(type(report.get('attempt')) is int and report['attempt'] in (1, 2), '最多两轮修正')
    require(isinstance(report.get('reviewer'), str) and report['reviewer'].strip(), '缺少评估者')
    level = report.get('level')
    require(level in ('patch', 'method', 'expansion'), '修改等级错误')
    old, new = cases(before), cases(after)
    require(all(new.get(k) == v for k, v in old.items()), '不得删除或放宽旧案例')
    require(before['evals/rubric.md'] == after['evals/rubric.md'], '标准改变需单独规划')
    changed = {k for k in FILES if before[k] != after[k]}
    require(changed - {'version.json', 'CHANGELOG.md'}, '没有实际修正')
    if level == 'patch':
        require(changed <= PATCH_FILES, 'patch 不能改导师方法、来源或维护代码')
    a = tuple(map(int, json.loads(before['version.json'])['version'].split('.')))
    b = tuple(map(int, json.loads(after['version.json'])['version'].split('.')))
    require(b == {'patch': (a[0], a[1], a[2] + 1), 'method': (a[0], a[1] + 1, 0),
                  'expansion': (a[0] + 1, 0, 0)}[level], '版本增量与等级不匹配')
    results = report.get('results')
    require(isinstance(results, list), '缺少对比结果')
    rows = {r.get('id'): r for r in results}
    require(len(rows) == len(results) and set(rows) == set(new), '必须覆盖全部案例且不能重复')
    for row in rows.values():
        require(row.get('baseline') in ('pass', 'fail') and row.get('candidate') == 'pass',
                '有未执行、失败或退步的候选测试')
        require(isinstance(row.get('reason'), str) and row['reason'].strip(), '缺少行为依据')
        for key in ('baseline_evidence', 'candidate_evidence'):
            relative = row.get(key)
            require(isinstance(relative, str) and not Path(relative).is_absolute(), '证据需相对维护目录定位')
            p = no_links(state / relative)
            require(inside(p, state / 'evaluations') and p.is_file() and 0 < p.stat().st_size <= LIMIT,
                    '证据缺失或越界')
    targets = report.get('target_cases')
    require(isinstance(targets, list) and targets and len(targets) == len(set(targets)) and
            set(targets) <= set(rows), '目标案例错误')
    require(any(rows[t]['baseline'] == 'fail' for t in targets), '目标未复现，不发布无证据更新')
    if level != 'patch':
        require(approval_path is not None, '方法或范围改变需真实用户确认文件')
        approval = read_json(approval_path)
        require(approval.get('candidate_sha256') == fingerprint(after) and approval.get('level') == level
                and isinstance(approval.get('confirmation'), str) and approval['confirmation'].strip(),
                '确认文件不对应当前候选')
    return before, after, dict(level=level, changed=sorted(changed), cases=len(rows),
                               candidate_sha256=fingerprint(after))

def apply(root, blobs, expected=None):
    if expected is not None:
        require(inventory(root) == expected, '源在评估后变化，拒绝覆盖未评估编辑')
    for name in FILES:
        no_links(root / name)
    for name in FILES:
        if expected is not None:
            require((root / name).read_bytes() == expected[name], '应用期间源文件变化: ' + name)
        write(root / name, blobs[name])

def rollback_source(root, before, after):
    conflicts = []
    for name in FILES:
        p = no_links(root / name)
        current = p.read_bytes()
        if current == after[name]:
            write(p, before[name])
        elif current != before[name]:
            conflicts.append(name)
    require(not conflicts, '保留并发编辑；需人工核对恢复: ' + ', '.join(conflicts))

def journal(state, event, data):
    with no_links(state / 'operations.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(event=event, at=datetime.now(timezone.utc).isoformat(), **data),
                           ensure_ascii=False) + '\n')

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('check')
    for name in ('init-state', 'snapshot'):
        q = sub.add_parser(name)
        q.add_argument('--state-root', type=Path)
    q = sub.add_parser('package')
    q.add_argument('--output', required=True, type=Path)
    q.add_argument('--state-root', type=Path)
    q = sub.add_parser('inspect')
    q.add_argument('--archive', required=True, type=Path)
    for name in ('gate', 'release'):
        q = sub.add_parser(name)
        q.add_argument('--candidate', required=True, type=Path)
        q.add_argument('--report', required=True, type=Path)
        q.add_argument('--state-root', type=Path)
        q.add_argument('--approval-file', type=Path)
        if name == 'release':
            q.add_argument('--output', required=True, type=Path)
    q = sub.add_parser('restore')
    q.add_argument('--snapshot', required=True, type=Path)
    q.add_argument('--state-root', type=Path)
    q.add_argument('--output', required=True, type=Path)
    args = p.parse_args(argv)
    root = no_links(args.source)
    blobs = inventory(root)
    if args.command == 'check':
        result = validate(blobs)
    elif args.command == 'package':
        if args.state_root or (root.parent.name == 'skills' and root.parent.parent.name == '_agent'):
            state = state_path(root, args.state_root)
            require(not inside(args.output, state), '安装包不能写入维护数据目录')
            with locked(state):
                result = dict(archive=str(package(blobs, root, args.output, state)), sha256=fingerprint(blobs))
        else:
            result = dict(archive=str(package(blobs, root, args.output)), sha256=fingerprint(blobs))
    elif args.command == 'inspect':
        entries = {NAME + '/' + k: v for k, v in blobs.items()}
        require(archive_read(args.archive, entries) == entries, '安装包与当前源不一致')
        result = dict(verified=True, files=len(entries), sha256=fingerprint(blobs))
    else:
        state = state_path(root, args.state_root)
        if args.command == 'gate':
            _, _, result = gate(root, args.candidate, args.report, state, args.approval_file)
        else:
            with locked(state):
                if args.command == 'init-state':
                    result = dict(state_root=str(state))
                elif args.command == 'snapshot':
                    result = dict(snapshot=str(snapshot(inventory(root), state)))
                else:
                    if args.command == 'release':
                        before, after, detail = gate(root, args.candidate, args.report, state, args.approval_file)
                    else:
                        snap = no_links(args.snapshot)
                        require(inside(snap, state / 'versions'), '恢复只能用本维护目录的快照')
                        before, after = inventory(root), read_snapshot(snap)
                        detail = dict(restored_version=validate(after)['version'])
                    require(not inside(args.output, root), '安装包不能写入源目录')
                    require(not inside(args.output, state), '安装包不能写入维护数据或历史快照目录')
                    log = no_links(state / 'operations.jsonl')
                    # Open before any source mutation; a directory/read-only log must fail early.
                    with log.open('a', encoding='utf-8'):
                        pass
                    output = no_links(args.output)
                    previous_package = output.read_bytes() if output.exists() else None
                    if previous_package is not None:
                        prior = archive_read(output, [NAME + '/' + k for k in FILES])
                        validate({k.removeprefix(NAME + '/'): v for k, v in prior.items()})
                    old = snapshot(before, state)
                    require(inventory(root) == before, '源在评估后变化，拒绝覆盖未评估编辑')
                    installed_package = None
                    try:
                        apply(root, after, expected=before)
                        package(after, root, args.output, state)
                        installed_package = output.read_bytes()
                        journal(state, args.command, dict(detail, previous_snapshot=old.name, sha256=fingerprint(after)))
                    except Exception:
                        # Preserve edits not made by this operation rather than blindly overwriting them.
                        if installed_package is not None and output.exists():
                            require(output.read_bytes() == installed_package, '安装包有并发编辑，需人工恢复')
                            if previous_package is not None:
                                write(output, previous_package)
                            else:
                                aborted = state / 'versions' / ('aborted-package-' + sha(installed_package)[:16]
                                          + '-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f') + '.skill')
                                require(not aborted.exists(), '中止安装包留存路径冲突')
                                output.replace(aborted)
                        rollback_source(root, before, after)
                        raise
                    result = dict(detail, previous_snapshot=str(old), archive=str(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, UnicodeError) as e:
        raise SystemExit('维护操作未完成: ' + str(e))

