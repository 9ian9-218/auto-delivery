# -*- coding: utf-8 -*-
"""test_isolation.py — check_isolation 的单元回归。

只测判据本身：manifest 解析、glob 展开、写死路径识别、配置绕道识别、PII 指纹。
不跑整仓自检（那是 check_isolation.py 的活），不连网、不读写真实用户数据。

跑法：python work/tests/test_isolation.py   或   pytest work/tests/test_isolation.py
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "work" / "tools"))

import check_isolation as ci  # noqa: E402
import pack_release as pr     # noqa: E402

# 样本一律运行期拼装：本文件自己也要过 PII 闸门与写死路径检查
BS = chr(92)          # 反斜杠
DRIVE = "C" + ":" + BS


def _write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_manifest_parse():
    tmp = Path(tempfile.mkdtemp(prefix="iso-manifest-"))
    man = _write(tmp / "m.manifest", "\n".join([
        "# 注释", "", "[functional]", "a/*.py", "b.md", "[generated]", "data/**",
    ]))
    got = ci.load_manifest(man)
    assert got["functional"] == ["a/*.py", "b.md"], got
    assert got["generated"] == ["data/**"], got


def test_manifest_rejects_orphan_and_empty():
    tmp = Path(tempfile.mkdtemp(prefix="iso-bad-"))
    orphan = _write(tmp / "o.manifest", "a.py\n[functional]\nb.py\n")
    try:
        ci.load_manifest(orphan)
    except ValueError as e:
        assert "段之前" in str(e), e
    else:
        raise AssertionError("段外条目应当报错")

    empty = _write(tmp / "e.manifest", "[functional]\n")
    try:
        ci.load_manifest(empty)
    except ValueError as e:
        assert "[functional]" in str(e), e
    else:
        raise AssertionError("空 functional 应当报错")


def test_expand_and_empty_glob():
    tmp = Path(tempfile.mkdtemp(prefix="iso-expand-"))
    _write(tmp / "work" / "tools" / "a.py", "x = 1\n")
    _write(tmp / "work" / "tools" / "b.py", "y = 2\n")
    _write(tmp / "docs" / "adr" / "0001.md", "# adr\n")
    found, empty = ci.expand(tmp, ["work/tools/*.py", "docs/**", "nothing/*.py"])
    assert set(found) == {"work/tools/a.py", "work/tools/b.py", "docs/adr/0001.md"}, found
    assert empty == ["nothing/*.py"], empty
    # 可移植写法：Python 3.11 的 "x/**" 只返回目录，"x/**/*" 才含文件
    nested, _ = ci.expand(tmp, ["docs/**/*"])
    assert set(nested) == {"docs/adr/0001.md"}, nested


def test_hardcoded_path_detected():
    tmp = Path(tempfile.mkdtemp(prefix="iso-hard-"))
    bad = _write(tmp / "bad.py", 'HOME = r"%sUsers%s bob"\n' % (DRIVE, BS))
    good = _write(tmp / "good.py", 'HOME = os.environ.get("HOME", "")\n')
    hits = ci.scan_hardcoded([bad], root=tmp)
    assert len(hits) == 1 and hits[0][2] == "本机用户目录", hits
    assert ci.scan_hardcoded([good], root=tmp) == []


def test_hardcoded_path_can_be_suppressed():
    tmp = Path(tempfile.mkdtemp(prefix="iso-noqa-"))
    p = _write(tmp / "x.py", 'P = r"%sUsers%s bob"  # noqa: isolation\n' % (DRIVE, BS))
    assert ci.scan_hardcoded([p], root=tmp) == []


def test_seam_bypass_detected():
    tmp = Path(tempfile.mkdtemp(prefix="iso-seam-"))
    name = "mail" + "_auth.json"
    bad = _write(tmp / "bad.py", 'AUTH = os.path.join(ROOT, "work", "%s")\n' % name)
    good = _write(tmp / "good.py",
                  "from user_config import cfg\nAUTH = cfg.resolve(cfg.need('mail', 'auth_file'))\n")
    hits = ci.scan_seam([bad, good], root=tmp)
    assert len(hits) == 1 and hits[0][0] == "bad.py", hits
    assert ci.scan_seam([good], root=tmp) == []


def test_seam_exempt_table_is_honoured():
    tmp = Path(tempfile.mkdtemp(prefix="iso-exempt-"))
    rel = "work/tools/pack_release.py"
    p = _write(tmp / rel, 'EXCLUDE = ["%s"]\n' % ("user" + "_config.json"))
    assert ci.scan_seam([p], root=tmp) == []


def test_pii_fingerprints():
    """复用 pack_release 的指纹，确保自检与打包闸门是同一套规则。"""
    idno = "331082" + "19990101" + "4038"
    phone = "137" + "12345678"
    auth = "auth_code: " + "RK" + "8ZK2M4Q9"
    for sample, rule in ((idno, "身份证号"), (phone, "手机号"), (auth, "授权码")):
        got = [n for n, rx in pr.PII_RULES if rx.search(sample)]
        assert rule in got, (sample, rule, got)
    # 占位符与公开企业邮箱不得误报
    for sample in ("<手机号>", "someone@example.com", "HR@x.com"):
        line = sample
        allowed = (any(a in line for a in pr.PII_ALLOW)
                   or any(m in line for m in pr.PLACEHOLDER_MARKERS)
                   or bool(pr.DOC_EXAMPLE.search(line)))
        hits = [] if allowed else [n for n, rx in pr.PII_RULES if rx.search(line)]
        assert hits == [], (sample, hits)


def test_manifest_covers_real_repo():
    """真仓的 manifest 必须可解析、无空 glob、且把自检脚本自己算作功能。"""
    man = ci.load_manifest()
    found, empty = ci.expand(REPO, man["functional"])
    assert not empty, empty
    assert "work/tools/check_isolation.py" in found
    assert "work/release.manifest" in found
    assert "work/mail_auth.example.json" in found


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print("ok  %s" % fn.__name__)
    print("PASS  isolation 判据 %d 组" % len(tests))
