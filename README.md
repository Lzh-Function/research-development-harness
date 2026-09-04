# Research Development Harness (RDH)

**AI に実装させながら、研究の「なぜ・何を・何が分かったか」を失わないための、repository 内で完結する開発 Harness。**

---

## 1. これは何を解決するのか

Claude Code や Codex に研究コードを書かせると、こうなりがちです。

> 3 日前に AI と一緒に組んだ probe、なんでこの設計にしたんだっけ。
> label 定義、途中で変えた気がする。どっちが正しいんだ。
> この AUROC、結局何を言えることになってたっけ。
> 明日 Codex に続きを頼みたいけど、あの会話もう流れた。

コードは増えたのに、**それが何だったのかが残っていない**。これを cognitive debt と呼びます。

RDH は AI の速度を落としません。落とす代わりに、次の 4 つを GitHub 上に残し、**本当に人間が決めるべき瞬間だけ**研究者を呼びます。

| 残すもの | どこに残るか |
|---|---|
| **Intent** なぜ・何をやるのか | Work Issue + 採択された Decision Record |
| **Implementation** どう作ったか | Git |
| **Evidence** 何が観測されたか | Result Record |
| **Understanding** 研究者が何を理解しているか | Gate Record |

**会話履歴は source of truth ではありません。** 明日別の AI が、会話ゼロの状態で作業を再開できることが要件です。

---

## 2. 全体像

登場人物は 3 者です。

```
   研究者 ── 意味の決定（Human Gate）だけを担当
     │
     ▼
   Agent（Claude Code / Codex）── 実装と、意味の解釈・文章化
     │  Skill 経由で呼ぶ
     ▼
   rh（repository 内の Python CLI）── Git / GitHub の決定論的な操作だけ
     │
     ▼
   Git + GitHub Issue / Draft PR ── 研究状態の永続化先
```

役割分担は厳密です。

- **`rh` は科学的判断をしません。** 「この変更は研究上重要か」を CLI が判断することはありません。
- **Agent は Git 状態を記憶に頼りません。** 「今どの branch か」「checkpoint はあるか」は必ず `rh` に訊きます。

`.research-harness/` 配下に、workflow 本文・policy・template・runtime がすべて入ります。`.claude/skills/` と `.agents/skills/` に置かれる 8 つの Skill は、その workflow を読みに行くだけの薄い入口です。

---

## 3. 導入

### 必要なもの

対象 repository 側に **Python 3.11+ / git / gh** があること。それだけです。

`pip install` も `npm install -g` も不要で、**`$HOME` には一切ファイルを作りません**（`.claude`、`.codex`、`.local`、`bin`、shell rc、どれも触りません）。これは文書上の約束ではなく、一時 HOME を command 実行前後で比較する test で実測しています。

### 入れる

この repository を clone して、研究 repository を指定するだけです。

```bash
git clone git@github.com:Lzh-Function/research-development-harness.git
cd research-development-harness
./bin/rh adopt ~/work/chirality-gnn
```

何が起きるか事前に見たいときは `--dry-run` を付けてください。

導入は **Overlay** です。既存の研究コードは 1 byte も変更されません。既存の `AGENTS.md` / `CLAUDE.md` は marker で囲まれた内側だけが追記され、外側は完全に保持されます。branch の rename も履歴の書き換えもしません。未 commit の作業も、そのまま残ります。

書き込まれるのは以下だけです。

```
.research-harness/**        ← workflow・policy・template・runtime
.claude/skills/rh-*/**      ← Claude Code 用の 8 skill
.agents/skills/rh-*/**      ← Codex 用の 8 skill
AGENTS.md / CLAUDE.md       ← marker の内側だけ
```

導入後、生成物を commit してください。これで、その repository を clone した誰もが（この distribution repository なしで）そのまま使えます。

```bash
cd ~/work/chirality-gnn
git add .research-harness .claude .agents AGENTS.md CLAUDE.md
git commit -m "Research Development Harness を導入"
```

### 動作確認

```bash
.research-harness/bin/rh doctor
```

```
INFO    python: Python 3.12.4
INFO    git: git version 2.45.0
INFO    github-remote: mylab/chirality-gnn
INFO    gh: GitHub CLI available
INFO    gh-auth: authenticated
INFO    installation: runtime 0.1.0, bundle 0.1.0, adopted 2026-09-04T10:09:59Z
INFO    claude-skills: 8 skills installed
INFO    codex-skills: 8 skills installed
INFO    managed-block: AGENTS.md contains the RDH managed block
INFO    outbox: empty
INFO    home-hygiene: no RDH files under $HOME

worst severity: INFO
```

`ERROR` が無ければ完了です。

---

## 4. ある一日 — キラリティ情報の消失層を特定する

深層学習 × ケモインフォマティクスの実際の流れで追います。

**設定**: GNN で分子物性を予測している。「キラリティ情報が message passing のどの層で失われるのか」を調べたい。

以下の `rh` は `~/work/chirality-gnn/.research-harness/bin/rh` の略です。Agent は毎回 `git rev-parse --show-toplevel` から解決するので、どの subdirectory にいても構いません。

### 9:00 — 研究者「キラリティがどこで消えるか調べたい」

Agent に `rh-scope` を使わせます。Agent は目的・方法・data flow・前提・「何が言えないか」を書いた scope 案を出し、**研究者の合意を取ってから** Issue を作ります。

```bash
rh issue create \
  --title "Chirality probe across message passing layers" \
  --kind experiment --risk high --evidence-required --rq 3 \
  --body-file scope.md
```

```
created Work Issue #1: https://github.com/mylab/chirality-gnn/issues/1
Next: take the Design Gate if required, then `rh work start 1`.
```

`--risk` は **行数ではなく研究上の影響**で決めます。boilerplate 5000 行より、label 定義を変える 10 行のほうが high です。`--evidence-required` は「この作業は科学的な証拠を生む」という宣言で、後で Evidence Gate が必須になります。

作った Issue を今の branch に紐付けます。

```bash
rh work link 1
rh status
```

```
Current Work         #1 Chirality probe across message passing layers
Derived State        DESIGN_GATE  — the design gate has no passing Gate Record yet
Risk                 high (experiment, evidence required)
Issue                #1
PR                   -
Branch               main
Latest Checkpoint    (none)
Pending Gates        design, evidence, knowledge
Blockers             (none)
Next Recorded Action (none)
```

**`Derived State` は専用 DB ではなく、Git と GitHub と record から毎回計算されます。** high risk なので gate が 3 つ立っています。

### 9:20 — Gate A（Design）: 研究者が設計を理解しているか

Agent が open-ended に問います。チェックリストの読み上げではなく、曖昧な点を訊きます。

> - この probe の AUROC は、何を測っていることになりますか
> - random split ではなく scaffold split を使う理由は
> - AUROC が下がったとき、それは情報が消えたことを意味しますか
> - この設計では何が**言えない**ですか

ここで研究者が「AUROC が下がった層で情報が消えている」と答えたとします。これは誤解です。Agent は勝手に補完して通さず、**修復してから研究者に言い直させます**。

通ったら記録します。保存されるのは outcome と概念だけで、**問答の全文は残しません**。

```bash
rh record gate --gate design --outcome passed --body-file gate-a.md
```

Gate は skip できます。研究者が上位の意思決定者です。

```bash
rh record gate --gate design --outcome overridden \
  --body "探索的プロトタイプのため今回は skip。"
```

### 9:40 — 作業開始

```bash
rh work start 1
```

```
branch    rh/1-chirality-probe-across-message-passing-layers
issue     #1
pushed    True
draft PR  #1000 https://github.com/mylab/chirality-gnn/pull/1000
note      uncommitted changes were preserved untouched
```

branch を切り、push し、**Draft PR** を開きます。Draft PR は「実装の台帳」です。既存 branch で作業中なら `--existing-branch probe-analysis` で取り込めます（**rename しません**）。

design gate が未取得だと、ここで止まります。これは提案ではなく precondition です。

```
rh: issue #1 requires a design gate before work starts
  hint: Run the Design Gate, then `rh record gate --gate design --outcome passed|overridden`.
```

ここから実装は AI の速度で進みます。変数名・型・fixture・logging・軽い refactor で研究者は**呼ばれません**。

### 11:30 — Gate B（Deviation）: 作業の意味が変わった

ChEMBL の 12% で R/S ラベルが未定義であることが判明しました。これは実装の詳細ではなく **label 定義の問題**なので、Agent は勝手に決めずに止まります。

Agent は選択肢と推奨を提示し、研究者が決め、決定を記録します。

```bash
rh record decision --status accepted --body-file decision.md
```

決定内容（抜粋）:

```markdown
### Trigger
ChEMBL の R/S ラベルが 12% の分子で未定義だった。

### Options
1. 未定義を除外 — n が 12% 減るが、ラベル定義が明確
2. RDKit で再割り当て — n を保てるが、ラベル生成過程がモデルと相関しうる

### Research Impact
option 2 は probe が RDKit の規則を学習する confounder を生む。

### Decision
option 1 を採用。n の減少より、ラベル定義の明確さを優先する。
```

**Issue 本文は書き換えません。** 現在の intent は「元の Issue + 採択された Decision Record」として解釈されるので、当初の意図が消えません。

止まるべき変更は: research question / target / label 定義 / dataset 定義 / 実験的妥当性 / metric の意味 / 大きな architecture / 永続的 API / scope の実質的拡大 / 大きな計算コスト / 解釈。

### 12:40 — 長時間実験の前に checkpoint

sweep を投げる前に、状態を残します。

```bash
rh record checkpoint --phase validating --body-file checkpoint.md
```

`--phase` は「今この作業が何をしているか」の申告です（`implementing` / `validating` / `blocked` / `review`）。**CLI は diff から「実験中か」を推測しません。**

checkpoint は作業日記ではなく、**会話履歴ゼロの新しい session が続きを書けるだけの最小情報**です。

```markdown
### Done
- layer 別 probe を実装 / ラベル未定義分子を除外

### Current State
probe.py が layer 0-5 の embedding を書き出す。sweep は未実行。

### Blocked By
none

### Next Action
sbatch scripts/sweep.sh を投入し、完了後に AUROC を集計する
```

`Blocked By` に `none` 以外を書くと、`rh` はそれを blocker として扱います。

### 13:00 — 計算ノードは network に出られない

問題ありません。record は outbox に退避します。

```bash
rh record checkpoint --body-file checkpoint.md
```

```
could not reach GitHub — checkpoint record c58c350d-... queued in the outbox
  reason: GitHub is unreachable: dial tcp: lookup api.github.com: ...
Run `rh sync` when GitHub is reachable; replay is idempotent.
```

退避中も `rh status` は正しく動きます（local cache + outbox を読みます）。

login ノードに戻ったら送ります。**同じ record が二重投稿されることはありません**（UUID で判定）。

```bash
rh sync
```

```
pending    1
posted     1
duplicate  0 (already on GitHub; not reposted)
failed     0
```

### 翌 9:00 — 別の AI が、会話ゼロで続きを引き継ぐ

昨日は Claude、今日は Codex。会話は残っていません。**ここが RDH の中心機能です。**

Agent に `rh-resume` を使わせます。

```bash
rh resume
```

```
state               VALIDATING
issue               #1
pr                  #1000
records             3
accepted decisions  1
results             0
latest checkpoint   2026-09-04T10:09:26.993Z
changes since       2 path(s)
next action         sbatch scripts/sweep.sh を投入し、完了後に AUROC を集計する
```

Agent はこれと `--json` の中身（Issue 本文、採択済み Decision、Result、checkpoint、checkpoint 以降の Git 差分）から、こういう briefing を組み立てます。

```
WHY                 GNN のどの層でキラリティ情報が失われるか（RQ #3）
WHAT                layer 別 linear probe で AUROC を測る
CURRENT STATE       VALIDATING / rh/1-chirality-probe... / PR #1000
DONE                probe 実装、ラベル未定義 12% を除外
IMPORTANT DECISIONS ラベル未定義は除外（RDKit 再割り当ては confounder のため不採用）
KNOWN EVIDENCE      まだ無い
LIMITATIONS         線形読み出し可能性の話であり、情報の有無ではない
UNRESOLVED          evidence gate、knowledge gate
NEXT                sweep を投入し AUROC を集計する
```

**Issue の記述と実際のコードが食い違っていたら**、Agent は黙って辻褄を合わせず `STATE DIVERGENCE DETECTED` と宣言し、未記録の drift か、意図的だが未記録の変更か、古い checkpoint かを切り分けます。研究上重要なら Deviation Gate に回します。

### 14:00 — 結果が出た。仮説は支持されなかった

layer 0 で AUROC 0.94、layer 5 で 0.52。Result Record を残します。**観測と解釈を厳密に分けます。**

```bash
rh record result --body-file result.md
```

```markdown
### Observation
layer 0 で AUROC 0.94、layer 3 で 0.71、layer 5 で 0.52。

### Supports
キラリティ情報が線形に読み出せる度合いは深層で低下する。

### Does NOT Support
情報が「失われている」こと。非線形に保持されている可能性を排除できない。

### Confounders
probe の容量が固定であるため、表現の非線形化と情報消失を区別できない。

### Provenance
- configuration: configs/probe_v2.yaml
- dataset: ChEMBL 34 stereo pairs / seed: 0-4 / run ID: slurm-88213
```

生ログは GitHub に置きません。**置くのは pointer だけ**です。

**仮説が支持されなくても、それは完了した実験です。** 失敗ではありません。

```bash
rh status
```

```
Derived State        EVIDENCE_GATE  — Result Records exist but the evidence gate has not passed
Pending Gates        evidence, knowledge
```

### 14:30 — Gate C（Evidence）: 主張の強さは研究者が決める

Agent は観測事実・可能な解釈・対立解釈・confounder を整理するところまでやり、**結論は確定させません**。

```bash
rh record gate --gate evidence --outcome passed --body-file gate-c.md
```

### 16:00 — 仕上げ

```bash
rh ready
```

```
NOT READY_TO_MERGE:
  - knowledge gate has no passing Gate Record
  - worktree has uncommitted changes
```

何が足りないかが決定論的に出ます。Agent に `rh-finish` を使わせ、**記憶ではなく record から** PR 本文を合成します。

```bash
rh pr update --body-file pr.md
```

そして Gate D（Knowledge）。「この作業を研究者本人が所有できているか」を確認します。関数名や行番号は訊きません。

> - この PR を一文で説明してください
> - 元の research question は
> - validation は何を保証し、何を保証しませんか
> - この evidence から何が言えて、何が言えませんか

説明できなければ通しません。修復して言い直してもらい、`repaired` として記録します。

```bash
rh record checkpoint --phase review --body-file final-checkpoint.md
rh record gate --gate knowledge --outcome repaired --body-file gate-d.md
rh ready
```

```
READY_TO_MERGE
The researcher merges. RDH never runs `gh pr merge`.
```

**ここで RDH は終わりです。merge は研究者が自分でやります。**

---

## 5. コマンド一覧と使いどころ

### 日常的に使うもの

| Command | いつ使うか |
|---|---|
| `rh status` | 「今どうなってる？」と思ったとき。まず最初にこれ |
| `rh resume` | session 開始時、AI を切り替えた後、状況が分からなくなったとき |
| `rh record checkpoint` | 作業の区切り、AI 切替前、長時間実験の前後、中断時、context 圧縮前 |
| `rh sync` | offline で作業した後、login ノードに戻ったとき |

### 作業単位のライフサイクル

| Command | いつ使うか |
|---|---|
| `rh issue create` | 新しい作業を scope し、研究者が合意した後 |
| `rh work link <n>` | 既存 branch を Work Issue に紐付ける／gate を記録する前 |
| `rh work start <n>` | 実装に着手するとき。branch + Draft PR を作る |
| `rh record decision` | 作業の**意味**が変わり、研究者が決めたとき |
| `rh record result` | 実験・解析が証拠を出したとき（支持されなくても） |
| `rh record gate` | 4 つの Human Gate それぞれの後 |
| `rh pr update` | 仕上げに PR 本文を合成するとき |
| `rh ready` | merge 可能か確認するとき |

### 管理・診断

| Command | いつ使うか |
|---|---|
| `rh doctor` | 導入直後、様子がおかしいとき。read-only |
| `rh audit` | 既存 repository を RDH に載せるとき。分類はしない inventory |
| `rh context` | Agent が最初に叩く。repo / branch / HEAD / Issue / PR / outbox |
| `rh adopt <path>` | 研究 repository に導入する（distribution repo から） |
| `rh upgrade <path>` | 新しい版を再導入する。local 変更は保護される |
| `rh version` | version 確認 |

**共通の作法**

- 読み取り系は `--json`、書き込み系は `--dry-run` が使えます。
- 長文は `--body-file <path>` を推奨します（`--body` も可）。GitHub 上の文字列が shell として解釈されることはありません。
- exit code `0` が成功。`rh ready` は未達なら非 0 を返すので、script に組み込めます。

### Skill と CLI の対応

研究者は基本的に Skill を呼ぶだけで、CLI を直接叩くのは Agent です。

| Skill | 中で使う CLI |
|---|---|
| `rh-scope` | `issue create`、`record gate --gate design` |
| `rh-start` | `work start` |
| `rh-checkpoint` | `record checkpoint` |
| `rh-resume` | `context`、`status`、`resume` |
| `rh-status` | `status` |
| `rh-decision` | `record decision`、`record gate --gate deviation` |
| `rh-result` | `record result`、`record gate --gate evidence` |
| `rh-finish` | `ready`、`pr update`、`record gate --gate knowledge` |

---

## 6. Human Gate は 4 つだけ

| Gate | いつ | 何を確認するか |
|---|---|---|
| **A. Design** | 実装前 | 目的と方法を研究者が理解し、合意しているか |
| **B. Deviation** | 意味が変わったとき | 勝手に scope を変えていないか |
| **C. Evidence** | 結果が出た後 | 主張の強さを研究者が決めたか |
| **D. Knowledge** | merge 前 | 研究者がこの作業を所有できているか |

outcome は `passed` / `repaired` / `overridden` / `blocked` の 4 つ。**保存されるのは outcome と概念だけで、問答の全文や思考過程は残しません。**

risk と gate の対応（`.research-harness/config.toml` で変更可）:

| risk | 例 | 必要な gate |
|---|---|---|
| **low** | typo、docs、logging、明らかな bug、test のみ | 原則なし |
| **medium** | 新しい解析 module、evaluation 追加、pipeline 変更 | Design / Knowledge（証拠を生むなら Evidence も） |
| **high** | model architecture、loss、data/label 定義、中心仮説、高コスト実験 | Design / Evidence / Knowledge |

**呼ばれない場面**: 関数名、class 構成、型、fixture、file 配置、通常の refactor、error handling、logging、lint、serialization、test の定型。

---

## 7. RDH が絶対にしないこと

以下は「推奨しない」ではなく、**code で拒否されます**。

```
git reset --hard    git clean        git stash        git restore
git rebase          commit --amend   履歴の書き換え
push --force        --force-with-lease
branch / tag / ref の削除            Issue の削除     gh pr merge
```

未 commit の作業は常に保持されます。branch 切替で Git が拒否した場合も、stash や reset で「どかす」ことはせず、error として報告します。これらが本当に必要なときは、研究者自身が実行してください。

そして **`READY_TO_MERGE` が終端です。merge は人間がやります。**

---

## 8. つまずきやすい点

**Q. `rh record gate` が「not linked to a Work Issue」と言う**
Issue を作った直後は branch と紐付いていません。`rh work link <n>` するか、`--issue <n>` を渡してください。

**Q. branch 名が `rh/12` だけになる**
title が日本語だと ASCII slug が空になるためです。説明的な branch 名が欲しい場合は、自分で branch を作って `rh work start 12 --existing-branch probe-analysis` としてください。

**Q. 既に走っている研究に途中から入れたい**
できます。`rh audit` で Agent に repository の inventory を渡し、`.research-harness/baseline.md`（導入時の snapshot）を研究者と一緒に埋め、進行中の branch を `--existing-branch` で取り込みます。**過去 100 commit を Issue 化したり、branch を rename したりはしません。** 目的は過去の完璧な整理ではなく、今日から迷子にならないことです。

**Q. 複数の AI を同時に走らせたい**
branch を分けてください（作業 A → branch A、作業 B → branch B）。同一 branch を 2 つの Agent が同時に書く運用は推奨しません。

**Q. `rh doctor` が gh で ERROR を出す**
`gh` が未 install か未認証です。RDH は `gh` を勝手に install しません。`gh auth login` してください。

---

## 9. 開発・検証

```bash
./run-tests -q
```

241 tests、standard library のみ、外部依存なしで動きます。GitHub は fake `gh` executable 経由で検証しているため、**自動 test に GitHub account も network も不要**です。

- authoritative な設計文書: [docs/SPEC.md](docs/SPEC.md)
- 実装上の判断と意図的な差分: [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)
- 要件と test の対応表: [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)
