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

## 4. Skill の呼び方

Skill は「明示的に呼ぶ」ことも「Agent が自分で選ぶ」こともできます。

| | Claude Code | Codex |
|---|---|---|
| **明示的に呼ぶ** | `/rh-resume` | `$rh-resume`（または `/skills` から選択） |
| **後ろに文を続ける** | `/rh-scope キラリティの消失層を調べたい` | `$rh-scope キラリティの消失層を調べたい` |
| **Agent が自分で選ぶ** | description に合致すれば自動 load | 同じく自動 load |

Skill 名の後ろに書いた文は、そのまま Agent に渡ります（Claude Code は `ARGUMENTS:` として付加します）。つまり **`/rh-scope` + いつも通りの依頼文**、という書き方で構いません。

自動 load もありますが、確実性は状況次第です。**実務上は、下の 4 つだけ明示的に打つ**ことをおすすめします。それ以外は普通にプロンプトを書けば、`AGENTS.md` / `CLAUDE.md` の managed block（毎 session 自動で読まれます）が Agent を harness に乗せます。

```
/rh-resume     ← session を始めるとき（最重要）
/rh-scope      ← 新しい作業を始めるとき
/rh-checkpoint ← 作業を止めるとき、長時間実験の前
/rh-finish     ← 仕上げるとき
```

---

## 5. ある一日 — キラリティ情報の消失層を特定する

深層学習 × ケモインフォマティクスの実際の流れを、**研究者が実際に打つプロンプト**とともに追います。

**設定**: GNN で分子物性を予測している。「キラリティ情報が message passing のどの層で失われるのか」を調べたい。

以下、`👤` が研究者の入力、`🤖` が Agent の挙動、`$ rh ...` が Agent が裏で実行するコマンド（と実際の出力）です。

---

### 9:00 — 新しい研究を始める

```
👤 /rh-scope GNN のどの層でキラリティ情報が失われるか調べたい。
   ChEMBL の立体異性体ペアを使って、layer ごとに linear probe をかける想定。
```

🤖 Agent は `rh context --json` で現在地を確認し、`.research-harness/workflows/scope.md` を読み、コードを眺めてから、**足りない情報だけ**訊いてきます。

> - split は random ですか、scaffold ですか
> - probe の入力は node embedding ですか、graph readout 後ですか
> - この実験、GPU 時間はどれくらい見ていますか

```
👤 scaffold split。node embedding のほう。3時間くらい。
```

🤖 scope 案（目的 / 方法 / data flow / 前提 / 何が言えないか）を提示し、risk 分類を宣言します。

> これは **high risk** と判断しました。probe の結論が「情報がどこで失われるか」という
> 中心的な主張に直結し、label 定義の選び方で結論が変わりうるためです。
> `evidence_required` も立てます。この分類でよいですか。

```
👤 いいよ、それで
```

**合意が取れてから** Issue を作ります。ここが一番安く間違えられる瞬間です。

```
$ rh issue create --title "Chirality probe across message passing layers" \
    --kind experiment --risk high --evidence-required --rq 3 --body-file scope.md

created Work Issue #1: https://github.com/mylab/chirality-gnn/issues/1
Next: take the Design Gate if required, then `rh work start 1`.
```

```
$ rh work link 1
$ rh status

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

`Derived State` は専用 DB ではなく、Git と GitHub と record から毎回計算されます。high risk なので gate が 3 つ立ちました。

---

### 9:20 — Gate A（Design）

**ここは追加のプロンプト不要**です。`rh-scope` の続きとして Agent が Design Gate に入ります。

🤖 チェックリストの読み上げではなく、曖昧な点を訊きます。

> - この probe の AUROC は、何を測っていることになりますか
> - random split ではなく scaffold split を使う理由は
> - AUROC が下がったとき、それは情報が消えたことを意味しますか
> - この設計では何が **言えない** ですか

```
👤 AUROC が下がった層で、キラリティ情報が消えてる
```

🤖 これは誤解です。Agent は**勝手に補完して通しません**。

> そこは切り分けが必要です。linear probe が測るのは「線形に読み出せるか」で、
> 情報の有無ではありません。表現が非線形になっただけでも AUROC は落ちます。
> この区別を踏まえると、AUROC が下がった層について何が言えますか。

```
👤 なるほど。「線形に読み出せなくなった」までしか言えなくて、
   消えたかどうかは MLP probe とか別の測り方が要る、ということか
```

🤖 通過。**問答の全文ではなく、outcome と概念だけ**を記録します。

```
$ rh record gate --gate design --outcome passed --body-file gate-a.md

recorded gate on issue #1: https://github.com/mylab/chirality-gnn/issues/1#issuecomment-100000
```

Gate は skip もできます。研究者が上位の意思決定者です。

```
👤 これ探索的に試すだけだから、design gate は飛ばして
```

```
$ rh record gate --gate design --outcome overridden \
    --body "探索的プロトタイプのため研究者判断で skip。"
```

---

### 9:40 — 実装に着手する

```
👤 /rh-start 1
```

```
$ rh work start 1

branch    rh/1-chirality-probe-across-message-passing-layers
issue     #1
pushed    True
draft PR  #1000 https://github.com/mylab/chirality-gnn/pull/1000
note      uncommitted changes were preserved untouched
```

branch を切り、push し、**Draft PR**（実装の台帳）を開きます。既存 branch で作業中なら:

```
👤 /rh-start 1 いま probe-analysis branch で書きかけのものがあるから、それを使って
```

```
$ rh work start 1 --existing-branch probe-analysis
```

既存 branch は **rename されません**。

design gate 未取得のまま着手しようとすると、ここで止まります。提案ではなく precondition です。

```
rh: issue #1 requires a design gate before work starts
  hint: Run the Design Gate, then `rh record gate --gate design --outcome passed|overridden`.
```

---

### 10:00〜11:30 — ここは普通にプロンプトを書くだけ

**Skill は要りません。** RDH は AI の速度を落とすためのものではありません。

```
👤 layer 0-5 の node embedding を書き出して、layer ごとに logistic probe をかけて。
   scaffold split で、seed は 0-4 の 5本
```

```
👤 probe の AUROC を CI 付きで出す集計スクリプトも
```

変数名、型、fixture の置き方、logging、軽い refactor — **こうしたことで研究者は呼ばれません**。Human-in-the-loop であって、Human-in-every-loop ではありません。

---

### 11:30 — Gate B（Deviation）: Agent のほうから止まる

ChEMBL の 12% で R/S ラベルが未定義であることが判明。これは実装の詳細ではなく **label 定義の問題**です。

🤖 **研究者が何も打っていないのに、Agent 側から止まります。** これが Deviation Gate です。

> 手が止まる判断が出ました。ChEMBL の 12% で R/S ラベルが未定義です。
> これは実装の選択ではなく label 定義の変更なので、勝手に決めません。
>
> **元の設計**: 全立体異性体ペアを使う
> **選択肢 1**: 未定義を除外 — n が 12% 減るが、ラベル定義は明確
> **選択肢 2**: RDKit で再割り当て — n は保てるが、ラベル生成過程がモデルと相関しうる
> **研究上の影響**: 選択肢 2 は probe が RDKit の規則を学習する confounder を生みます
> **推奨**: 選択肢 1

```
👤 1 で。n が減るより、ラベルの定義がはっきりしてるほうが大事
```

```
$ rh record decision --status accepted --body-file decision.md

recorded decision on issue #1: https://github.com/mylab/chirality-gnn/issues/1#issuecomment-100001
```

**Issue 本文は書き換えません。** 現在の intent は「元の Issue + 採択された Decision Record」として解釈されるので、当初の意図が消えません。

自分から相談したいときは明示的に呼べます。

```
👤 /rh-decision metric を AUROC から AUPRC に変えるべきか迷ってる
```

止まるべき変更: research question / target / label 定義 / dataset 定義 / 実験的妥当性 / metric の意味 / 大きな architecture / 永続的 API / scope の実質的拡大 / 大きな計算コスト / 解釈。

---

### 12:40 — 長時間実験の前に checkpoint

```
👤 /rh-checkpoint これから sweep 投げるので、いったん状態を残して
```

```
$ rh record checkpoint --phase validating --body-file checkpoint.md
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

---

### 13:00 — 計算ノードは network に出られない

問題ありません。record は outbox に退避します。

```
$ rh record checkpoint --body-file checkpoint.md

could not reach GitHub — checkpoint record c58c350d-... queued in the outbox
  reason: GitHub is unreachable: dial tcp: lookup api.github.com: ...
Run `rh sync` when GitHub is reachable; replay is idempotent.
```

退避中も `rh status` は正しく動きます（local cache + outbox を読みます）。login ノードに戻ったら:

```
👤 outbox に溜まってるやつ送っといて
```

```
$ rh sync

pending    1
posted     1
duplicate  0 (already on GitHub; not reposted)
failed     0
```

**同じ record が二重投稿されることはありません**（UUID で判定）。

---

### 翌 9:00 — 別の AI が、会話ゼロで続きを引き継ぐ

昨日は Claude、今日は Codex。会話は残っていません。**ここが RDH の中心機能で、明示的に呼ぶ価値が最も高い場面です。**

```
👤 $rh-resume
```

```
$ rh resume

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

🤖 Agent はこれと `--json` の中身（Issue 本文、採択済み Decision、Result、checkpoint、checkpoint 以降の Git 差分）から briefing を組み立てます。

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

ここまで来れば、あとは普通に続けられます。

```
👤 sweep 終わってるはずだから、結果を集計して
```

**Issue の記述と実際のコードが食い違っていたら**、Agent は黙って辻褄を合わせず `STATE DIVERGENCE DETECTED` と宣言し、未記録の drift か、意図的だが未記録の変更か、古い checkpoint かを切り分けます。研究上重要なら Deviation Gate に回します。

---

### 14:00 — 結果が出た。仮説は支持されなかった

layer 0 で AUROC 0.94、layer 5 で 0.52。

```
👤 /rh-result slurm-88213 の結果を記録して。configs/probe_v2.yaml、seed 0-4
```

🤖 **観測と解釈を厳密に分けて**書きます。

```
$ rh record result --body-file result.md
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
そして **仮説が支持されなくても、それは完了した実験です。** 失敗ではありません。

---

### 14:30 — Gate C（Evidence）

`rh-result` の続きとして、Agent が Evidence Gate に入ります。**結論は確定させません。**

> 観測事実はこうです。可能な解釈は 2 つあり、対立解釈として probe 容量の
> 問題が残ります。この evidence で、どこまで主張しますか。

```
👤 「線形読み出し可能性が単調に低下する」まで。
   情報の消失は主張しない。MLP probe を follow-up に回す
```

```
$ rh record gate --gate evidence --outcome passed --body-file gate-c.md
$ rh status

Derived State        EVIDENCE_GATE → 通過
Pending Gates        knowledge
```

---

### 16:00 — 仕上げ

```
👤 /rh-finish
```

```
$ rh ready

NOT READY_TO_MERGE:
  - knowledge gate has no passing Gate Record
  - worktree has uncommitted changes
```

🤖 足りないものが決定論的に出ます。Agent は **記憶ではなく record から** PR 本文を合成します。

```
$ rh pr update --body-file pr.md

updated PR #1000 body
```

続けて Gate D（Knowledge）。「この作業を研究者本人が所有できているか」を確認します。関数名や行番号は訊きません。

> - この PR を一文で説明してください
> - 元の research question は
> - validation は何を保証し、何を保証しませんか
> - この evidence から何が言えて、何が言えませんか

```
👤 GNN の layer を深くするとキラリティ情報が線形に読み出せなくなる、
   というのを probe で示した PR
```

🤖 まだ通しません。

> 「読み出せなくなる」と「失われる」の区別は、この PR の主張の核です。
> validation が保証しないことのほうを、もう一度説明してもらえますか。

```
👤 probe の容量が固定だから、表現が非線形になっただけの場合と
   情報が消えた場合を区別できてない。だから消失は主張できない
```

```
$ rh record checkpoint --phase review --body-file final-checkpoint.md
$ rh record gate --gate knowledge --outcome repaired --body-file gate-d.md
$ rh ready

READY_TO_MERGE
The researcher merges. RDH never runs `gh pr merge`.
```

**ここで RDH は終わりです。merge は研究者が自分でやります。**

---

### この一日で、研究者が明示的に打った Skill は 6 回だけ

```
/rh-scope      9:00   新しい作業を始めるとき
/rh-start      9:40   実装に着手するとき
/rh-checkpoint 12:40  長時間実験の前
$rh-resume     翌9:00 会話ゼロから引き継ぐとき（最重要）
/rh-result     14:00  結果が出たとき
/rh-finish     16:00  仕上げるとき
```

Gate A / B / C / D は、それぞれ `rh-scope` / Agent 側の自発的停止 / `rh-result` / `rh-finish` の中で起きるので、**Gate のために何かを打つ必要はありません**。それ以外の時間は、普通にプロンプトを書いているだけです。

---

## 6. コマンド一覧と使いどころ

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

研究者は Skill を呼ぶだけで、CLI を直接叩くのは Agent です。

| Skill | 呼び方 | 中で使う CLI | 含まれる Gate |
|---|---|---|---|
| `rh-scope` | 明示推奨 | `issue create`、`record gate --gate design` | **A. Design** |
| `rh-start` | 明示推奨 | `work start` | — |
| `rh-checkpoint` | 明示推奨 | `record checkpoint` | — |
| `rh-resume` | **明示必須に近い** | `context`、`status`、`resume` | — |
| `rh-status` | Agent 任せで可 | `status` | — |
| `rh-decision` | **Agent 側から発火** | `record decision`、`record gate --gate deviation` | **B. Deviation** |
| `rh-result` | 明示推奨 | `record result`、`record gate --gate evidence` | **C. Evidence** |
| `rh-finish` | 明示推奨 | `ready`、`pr update`、`record gate --gate knowledge` | **D. Knowledge** |

**4 つの Human Gate は、いずれも Skill の中で起きます。** Gate を開くために研究者が何かを打つ必要はありません。特に Deviation Gate は、研究者が何も言っていないときに Agent 側から止まるのが正常な動作です。

---

## 7. Human Gate は 4 つだけ

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

## 8. RDH が絶対にしないこと

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

## 9. つまずきやすい点

**Q. `rh record gate` が「not linked to a Work Issue」と言う**
Issue を作った直後は branch と紐付いていません。`rh work link <n>` するか、`--issue <n>` を渡してください。

**Q. branch 名が `rh/12` だけになる**
title が日本語だと ASCII slug が空になるためです。説明的な branch 名が欲しい場合は、自分で branch を作って `rh work start 12 --existing-branch probe-analysis` としてください。

**Q. 既に走っている研究に途中から入れたい**
できます。`rh audit` で Agent に repository の inventory を渡し、`.research-harness/baseline.md`（導入時の snapshot）を研究者と一緒に埋め、進行中の branch を `--existing-branch` で取り込みます。**過去 100 commit を Issue 化したり、branch を rename したりはしません。** 目的は過去の完璧な整理ではなく、今日から迷子にならないことです。

**Q. 複数の AI を同時に走らせたい**
branch を分けてください（作業 A → branch A、作業 B → branch B）。同一 branch を 2 つの Agent が同時に書く運用は推奨しません。

**Q. Skill を呼び忘れたらどうなるのか**
`AGENTS.md` / `CLAUDE.md` の managed block は毎 session 自動で読まれるので、Skill を呼ばなくても「chat history ではなく repo-local state から復元しろ」「medium/high は実装前に scope しろ」「checkpoint を残せ」までは Agent に届きます。ただし **これらは指示であって、hook による強制ではありません**。Agent が `rh` を一度も呼ばなければ RDH は何も起きません。技術的に硬いのは、Agent が `rh` を呼んだ後（design gate 未取得なら `rh work start` が exit 3 で止まる、など）だけです。**session 冒頭の `/rh-resume` だけは明示的に打つ**のが確実です。

**Q. `rh doctor` が gh で ERROR を出す**
`gh` が未 install か未認証です。RDH は `gh` を勝手に install しません。`gh auth login` してください。

---

## 10. 開発・検証

```bash
./run-tests -q
```

241 tests、standard library のみ、外部依存なしで動きます。GitHub は fake `gh` executable 経由で検証しているため、**自動 test に GitHub account も network も不要**です。

- authoritative な設計文書: [docs/SPEC.md](docs/SPEC.md)
- 実装上の判断と意図的な差分: [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md)
- 要件と test の対応表: [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)
