# Research Development Harness — 開発者向け指示

これは RDH **そのものを開発する** repository です（研究 project ではありません）。
このファイルは手書きの project 指示であり、RDH の managed block ではありません。

**作業を始める前に [docs/HANDOVER.md](docs/HANDOVER.md) を読むこと。** 何が出来ていて、
何が意図的にそうなっていて、何が欠けているかが、判断の理由ごと書いてあります。

## 絶対に侵さないこと

- **`$HOME` に一切書かない。** RDH の存在理由の一つ。canary 付きのテストで固定。
- **破壊的 Git 操作を実装しない。** reset --hard / clean / stash / force push / 履歴書き換え / branch 削除 / merge。`git.assert_safe_git` が拒否する。
- **CLI に科学的判断を入れない。** risk 判定、deviation 検知、checkpoint 自動生成はすべて Agent 側の仕事。
- **Skill は thin adapter のまま。** workflow 本文は `bundle/workflows/` に 1 箇所だけ。frontmatter は `name` と `description` のみ（他の field は Codex 側で invalid）。
- **この repo を RDH に self-adopt しない。** 意図的に未実施。

## 作法

```bash
./run-tests -q     # 全テスト。standard library のみ、pytest 不要
```

- **README の出力例は必ず実際に採取する。** 手で書かない。`tests/support.py` の `Sandbox` が使える。過去に作文した例が実装のバグを隠していた。
- **`gh` 呼び出しを足したら、[docs/GH-SURFACE.md](docs/GH-SURFACE.md) の許可リストも更新し、実 API でも 1 回叩く。** 許可リストはテストが実装と照合する。fake `gh` は 2 回、実挙動と食い違っていた。
- **`gh api` を使わない。** 任意の API を token 付きで叩けるため、token をエージェントから隔離する運用を壊す。fake `gh` は呼ばれると exit 99 で落ちる。
- テスト数を変えたら README 末尾と `docs/ACCEPTANCE.md` の数値も直す。
- commit message は日本語で、**何をしたか**より**なぜそうしたか**を書く。
