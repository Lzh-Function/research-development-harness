# Research Development Harness

研究開発のための、完全 repository-local な Human–AI 開発 Harness。

Claude Code や Codex は、研究者が理解できる速度をはるかに超えて研究コードを生成します。RDH はその速度を落としません。落とす代わりに、次の 4 つを失わないよう保持し、本当に人間の判断が必要な決定だけを研究者へ返します。

| 意味 | Canonical source |
|---|---|
| **Intent** — なぜ・何を | Work Issue + accepted Decision Records |
| **Implementation** — どう実現したか | Git |
| **Evidence** — 何が観測されたか | Result Records |
| **Understanding** — 研究者が何を所有しているか | Gate Records |

Human-in-the-loop であって、Human-in-every-loop ではありません。

## Deployment contract

RDH は **完全に repository-local** です。`$HOME` 配下には一切ファイルを作成・変更しません。`.claude`、`.agents`、`.codex`、`.local`、`bin`、`.config`、shell rc のいずれもです。global skill も、global `rh` も、install が必要な Python package もありません。

これは文書上の約束ではなく、temporary `HOME` を command の実行前後で snapshot 比較する integration test によって実測されています（[tests/integration/test_home_zero_touch.py](tests/integration/test_home_zero_touch.py)）。

対象 repository に必要なもの: **Python 3.11+**、**git**、**gh**。

## 研究 repository への導入

この repository の clone から実行します。

```bash
./bin/rh adopt /path/to/my-research-project
```

これで runtime と workflow が対象へ vendor されます。以降、対象 repository は自己完結し、この distribution repository を必要としません。事前確認には `--dry-run` を使ってください。

Adoption は **Overlay + Cutover** です。履歴を書き換えず、branch を rename せず、研究 source file を変更せず、`AGENTS.md` / `CLAUDE.md` は自身の marker の内側だけに触れます。書き込む対象は厳密に以下だけです。

```
.research-harness/**
.claude/skills/rh-*/**
.agents/skills/rh-*/**
AGENTS.md   — managed block のみ
CLAUDE.md   — managed block のみ
```

生成物は他の repository content と同様に commit してください。そうすることで、fresh clone がそのまま使える状態になります。

## 使い方

adopt 済み repository での CLI は次の通りです。

```bash
"$(git rev-parse --show-toplevel)/.research-harness/bin/rh" status
```

Agent は、Claude Code（`.claude/skills/`）と Codex（`.agents/skills/`）の双方へ配置される 8 つの project skill 経由でこれを利用します。`rh-scope`、`rh-start`、`rh-checkpoint`、`rh-resume`、`rh-status`、`rh-decision`、`rh-result`、`rh-finish` です。

各 skill は `.research-harness/workflows/` にある canonical workflow への thin adapter にすぎません。workflow の本文は 1 箇所にのみ存在し、vendor ごとに複製されていません。

典型的な work unit の流れ:

```
rh-scope      → Work Issue、risk 分類、[Gate A — Design]
rh-start      → branch + Draft PR
  … 実装し、意味のある区切りで checkpoint …
rh-decision   → 作業の意味が変わったとき [Gate B — Deviation]
rh-result     → Result Record、[Gate C — Evidence]
rh-finish     → PR synthesis、[Gate D — Knowledge]、READY_TO_MERGE
```

`READY_TO_MERGE` が RDH の責任範囲の終端です。**Harness は merge しません。**

## RDH が行わないこと

以下は文書上の禁止ではなく、code で拒否されます。

```
git reset --hard   git clean       git stash        git restore
git rebase         commit --amend  history rewrite
push --force       --force-with-lease
branch/tag/ref の削除               issue の削除     gh pr merge
```

未 commit の作業は常に保持されます。これらが本当に必要な場合は、研究者自身が実行してください。

## Commands

| Command | 役割 |
|---|---|
| `rh version` | runtime / bundle version |
| `rh doctor` | 環境と installation の read-only 診断 |
| `rh audit` | repository の read-only inventory（分類はしない） |
| `rh adopt <target>` | 研究 repository へ RDH を vendor |
| `rh upgrade <target>` | local 変更を保持したまま新しい RDH を再 vendor |
| `rh context` | repo、branch、HEAD、dirty 状態、紐付く Issue/PR、outbox |
| `rh status` | derived state、pending gates、blockers、next action |
| `rh resume` | fresh session が作業を継続するために必要な一式 |
| `rh issue create` | `rh:work` machine marker 付きの Work Issue |
| `rh work start\|link` | branch + Draft PR、または既存 branch の紐付け |
| `rh record checkpoint\|decision\|result\|gate` | Issue comment としての durable record |
| `rh ready` | `READY_TO_MERGE` の決定論的 precondition |
| `rh sync` | 退避済み record の再送（idempotent） |
| `rh pr update` | Draft PR body の置換 |

read command は `--json` を、mutation command は `--dry-run` を support します。exit code `0` が成功、それ以外は failure または precondition 未充足です。

## 設計上の境界

この分離こそが本システムの要点であり、厳密に守られています。

* **Agent / Skill** — research intent、risk 分類、Design Grill、semantic deviation detection、evidence の解釈、misconception repair、record と PR の文章生成、Knowledge Grill。
* **`rh` runtime** — Git / GitHub state、branch / Issue / PR 操作、record の parsing と serialization、context 収集、state derivation、gate prerequisite check、adoption、outbox、sync、doctor、upgrade、managed block。

CLI に scientific judgement は実装されていません。逆に、Git / GitHub の state 管理を自然言語だけに委ねてもいません。

## Offline 時の挙動

GitHub へ到達できなかった record は `.git/research-harness/outbox/` へ退避され、`rh sync` で再送されます。再送は idempotent です。UUID が既に Issue 上に存在する record は破棄され、二重投稿されません。`rh status --offline` は local cache から動作します。

## 開発

```bash
python3 -m unittest discover -s tests -t . -q
```

runtime と同じく standard library のみで、test 依存はありません。GitHub は fake `gh` executable（[tests/fixtures/fake_gh.py](tests/fixtures/fake_gh.py)）経由で検証されるため、自動 test に GitHub account も network も不要です。

authoritative な設計文書は [docs/SPEC.md](docs/SPEC.md) です。実装上の判断と意図的な差分は [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)、要件ごとの検証根拠は [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) にあります。
