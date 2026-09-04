# Research Development Harness
## Repository-Local Human–AI Research Development Harness
### Implementation Specification / System Design

**Specification Version:** 1.0  
**Target Initial Release:** v0.1  
**Primary Agents:** Claude Code / OpenAI Codex  
**SCM:** Git + GitHub  
**GitHub Interface:** GitHub CLI (`gh`)  
**Runtime:** Python 3.11+  
**Deployment:** Fully repository-local  
**Core principle:** Human-in-the-loop, but not Human-in-every-loop

---

# 0. Executive Summary

Research Development Harness（以下 **RDH**）は、Claude Code / Codex によって研究コードの生成・解析・実験実装が人間の理解速度を大幅に上回る環境で、

- なぜこの作業をしているのか
- 何を実装しているのか
- 途中で何が変わったのか
- 何が実験的に分かったのか
- 何がまだ言えないのか
- 研究者本人がどこまで理解しているのか
- 次に何をすべきなのか

を失わないための開発ハーネスである。

RDHはAIの実装速度を人間の速度まで落とさない。

代わりに、研究上重要な意味境界だけをHuman Gateとして人間に返す。

管理対象は次の4つとする。

```text
Intent
    なぜ・何を行うか

Implementation
    どう実現したか

Evidence
    実際に何が観測されたか

Understanding
    研究者本人が何を理解しているか
```

GitHubをこれらの永続的な「意味のindex」として使用する。

---

# 1. 最重要Deployment Contract

## 1.1 Repository-local only

RDHは **完全repository-local** でなければならない。

RDHは以下へファイルを作成・変更してはならない。

```text
$HOME/.claude/
$HOME/.agents/
$HOME/.codex/
$HOME/.local/
$HOME/bin/
$HOME/.config/
shell rc files
その他ユーザーglobal configuration
```

つまり、

> **RDH固有のglobal installationは存在しない。**

Codex / Claude Code / `gh` 自身が通常利用する既存の認証・設定は対象外である。

RDH自身がそれらを追加・変更してはならない。

---

## 1.2 Global Python package installも要求しない

以下をRDH利用の前提としてはならない。

```text
pip install ...
uv tool install ...
pipx install ...
npm install -g ...
cargo install ...
```

対象repoをcloneしただけで、Python 3.11+、Git、GitHub CLIがあればRDHが動作することを目標とする。

---

# 2. Distribution Model

RDHには二種類のrepositoryが存在する。

## A. Harness Distribution Repository

RDHそのものを開発するrepository。

```text
research-development-harness/
```

## B. Target Research Repository

RDHを導入される研究repository。

```text
my-research-project/
```

関係は次の通り。

```text
research-development-harness/
          │
          │ one-time adopt
          ▼
my-research-project/
          │
          └── .research-harness/
              .claude/skills/
              .agents/skills/
              AGENTS.md
              CLAUDE.md
```

---

# 3. Adoption

Harness distribution repositoryから、

```bash
./bin/rh adopt /path/to/research-project
```

を実行する。

これは対象repositoryへRDH runtimeとworkflowをvendorする。

一度adoptされた後、対象repositoryはHarness distribution repositoryを必要としない。

---

# 4. Target Repository Layout

adoption後の標準構造：

```text
research-project/
│
├── .research-harness/
│   ├── manifest.toml
│   ├── config.toml
│   │
│   ├── bin/
│   │   └── rh
│   │
│   ├── runtime/
│   │   └── research_harness/
│   │       ├── __init__.py
│   │       ├── cli.py
│   │       ├── git.py
│   │       ├── github.py
│   │       ├── records.py
│   │       ├── context.py
│   │       ├── state.py
│   │       ├── outbox.py
│   │       └── doctor.py
│   │
│   ├── policy/
│   │   ├── workflow.md
│   │   ├── human-gates.md
│   │   ├── records.md
│   │   └── safety.md
│   │
│   ├── workflows/
│   │   ├── scope.md
│   │   ├── start.md
│   │   ├── checkpoint.md
│   │   ├── resume.md
│   │   ├── decision.md
│   │   ├── result.md
│   │   ├── finish.md
│   │   └── status.md
│   │
│   └── templates/
│       ├── work-issue.md
│       ├── research-question.md
│       ├── pull-request.md
│       ├── checkpoint.md
│       ├── decision.md
│       ├── result.md
│       └── gate.md
│
├── .claude/
│   └── skills/
│       ├── rh-scope/
│       │   └── SKILL.md
│       ├── rh-start/
│       │   └── SKILL.md
│       ├── rh-checkpoint/
│       │   └── SKILL.md
│       ├── rh-resume/
│       │   └── SKILL.md
│       ├── rh-status/
│       │   └── SKILL.md
│       ├── rh-decision/
│       │   └── SKILL.md
│       ├── rh-result/
│       │   └── SKILL.md
│       └── rh-finish/
│           └── SKILL.md
│
├── .agents/
│   └── skills/
│       └── <same logical skills>
│
├── AGENTS.md
├── CLAUDE.md
│
└── existing research files
```

`.research-harness/`がvendor-neutralなcanonical implementation / workflowである。

`.claude/skills`と`.agents/skills`はthin adapterでなければならない。

---

# 5. Repository-local CLI

対象repoではcanonical CLIを、

```text
.research-harness/bin/rh
```

とする。

Skillから呼び出す場合はrepository rootを確定してから、

```bash
"$(git rev-parse --show-toplevel)/.research-harness/bin/rh" ...
```

相当の方法で呼び出す。

CWDがrepository rootであると仮定してはならない。

---

# 6. Runtime Requirements

必要な外部runtime：

```text
Python >= 3.11
git
gh
```

v0.1ではPython standard libraryのみをSHOULD useする。

主要候補：

```text
argparse
subprocess
pathlib
json
tomllib
tempfile
uuid
datetime
shutil
hashlib
```

外部Python dependencyを導入する場合は明確な必要性がなければならない。

---

# 7. Harness Distribution Repository Layout

RDHそのものは以下のような独立repositoryとして実装する。

```text
research-development-harness/
│
├── README.md
├── CHANGELOG.md
├── LICENSE
├── docs/
│   └── SPEC.md
│
├── bin/
│   └── rh
│
├── src/
│   └── research_harness/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── git.py
│       ├── github.py
│       ├── context.py
│       ├── state.py
│       ├── records.py
│       ├── adopt.py
│       ├── upgrade.py
│       ├── outbox.py
│       ├── doctor.py
│       └── util.py
│
├── bundle/
│   ├── policy/
│   ├── workflows/
│   ├── templates/
│   ├── claude-skills/
│   └── codex-skills/
│
└── tests/
    ├── unit/
    ├── integration/
    ├── e2e/
    └── fixtures/
```

distribution側`bin/rh`は`src/`を直接利用してよい。

`adopt`時に必要なruntimeをtargetの、

```text
.research-harness/runtime/
```

へcopyする。

---

# 8. Architecture

```text
                  Researcher
                       │
                Human Decisions
                       │
           ┌───────────▼───────────┐
           │ Claude / Codex Skills │
           │ Semantic reasoning    │
           └───────────┬───────────┘
                       │
                structured calls
                       │
               ┌───────▼───────┐
               │ repo-local rh │
               │ deterministic │
               └───────┬───────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
       Git           GitHub      Harness files
                     via gh
```

---

# 9. Responsibility Boundary

## Agent / Skill responsibility

LLMが担当する。

- Research Question理解
- Issue specification生成
- risk classification
- assumption抽出
- Design Grill
- semantic deviation detection
- scientific interpretation支援
- misconception repair
- checkpoint文章生成
- Result Record文章生成
- PR synthesis
- Knowledge Grill

---

## `rh` responsibility

決定論的に実装する。

- repository検出
- Git status
- branch / HEAD
- GitHub repository検出
- Issue / PR read
- Issue / PR creation
- comment record creation
- machine marker parsing
- current Work Issue特定
- record取得
- state inference
- gate presence検査
- outbox
- version compatibility
- managed-block update
- adoption
- upgrade
- doctor

---

# 10. Critical Design Rule

> **LLM logicをCLIへ埋め込まない。**

例えばCLIが、

> この変更は研究上重要だからHuman Gateを発火すべき

と自然言語内容から判断してはならない。

Agentがsemantic decisionを行い、

```text
rh record decision ...
```

等を利用する。

逆に、

> Issue #184に最新checkpointが存在するか

のような決定論的処理をLLM任せにしてはならない。

---

# 11. Research State Model

永続管理する意味は4つ。

```text
Intent
Implementation
Evidence
Understanding
```

対応：

| Meaning | Canonical source |
|---|---|
| Intent | Work Issue + accepted Decision Records |
| Implementation | Git |
| Evidence | Result Records |
| Understanding | Gate Records |
| Progress | latest Checkpoint + Gitとの差分 |

Agent chat historyはSource of Truthではない。

---

# 12. Core Research Flow

```text
Research Idea
     │
     ▼
Scope Draft
     │
     ▼
Researcher Scope Confirmation
     │
     ▼
Work Issue
     │
     ▼
[Gate A — Design / Intent]
     │
     ▼
Draft PR + Implementation
     │
     ├─────────────┐
     │             │ significant deviation
     │             ▼
     │      [Gate B — Deviation]
     │             │
     ◀─────────────┘
     │
     ▼
Validation / Experiment
     │
     ▼
[Gate C — Evidence]
     │
     ▼
PR Synthesis
     │
     ▼
[Gate D — Knowledge]
     │
     ▼
READY_TO_MERGE
```

Harness自身はmergeしない。

---

# 13. Human Gate A — Design / Intent

目的：

> 今から行う研究・実装を研究者自身が理解し、目的と方法に合意しているか。

Agentは以下を中心にopen-ended questionを生成する。

- 何を検証するのか
- なぜこの方法で問いに答えられるのか
- input → outputの主要data flow
- 主要assumption
- failure mode
- confounder
- 何が観測されれば仮説を支持/反証するか
- この解析から何は言えないか

Medium work：

```text
おおむね3〜5問
```

High work：

```text
おおむね5〜8問
```

理解確認が済めば固定問題数まで続ける必要はない。

---

# 14. Human Gate B — Deviation

Agentはroutine implementation detailではユーザーを止めない。

Human decisionが必要な主な変更：

```text
research question
target
label definition
dataset definition
experimental validity
metric semantics
major architecture
persistent public API
scope material expansion
large additional compute cost
interpretation
```

Agentは最低限、

```text
何が変わったか
なぜ変更が必要か
元の設計
選択肢
Agentの推奨
研究上・architecture上の影響
```

を提示する。

---

# 15. Human Gate C — Evidence

scientific resultについてAgentだけでconclusionを確定してはならない。

Agent：

```text
Observed facts
Possible interpretation
Alternative interpretation
Confounders
What this supports
What this does not establish
```

を整理する。

研究者が主張の強さを決定する。

negative resultも正常なcompleted experimentとして扱う。

---

# 16. Human Gate D — Knowledge

merge前に、

> 研究者本人がこのWork Unitを所有できる程度に理解しているか

を確認する。

代表的な問い：

```text
このPRを一文で説明してください。

元のResearch Questionは？

主要data flowは？

重要な設計判断は？

Issueから何が変わった？

Validationは何を保証する？

何は保証しない？

Evidenceから何が言える？

何は言えない？

次に何を調べる？
```

コードの関数名・行番号暗記を標準問題にしてはならない。

---

# 17. Grill Repair Loop

```text
Researcher answer
      │
      ├── sufficient
      │      └── next
      │
      ├── partial
      │      └── explain missing concept → retry
      │
      └── misconception
             └── repair → researcher restates
```

Agentが研究者の回答を勝手に補ってpassさせてはならない。

---

# 18. Gate Override

研究者はGateをoverrideできる。

例：

```text
exploratory prototypeなので今回はskip
```

Gate Recordには、

```text
outcome = overridden
reason = ...
```

だけを保存する。

Harnessが研究者より上位の意思決定主体になってはならない。

---

# 19. Work Risk

## LOW

例：

- typo
- docs
- logging
- obvious bug
- test-only
- behavioral changeなしのminor refactor

通常Gate不要。

---

## MEDIUM

例：

- 新しいanalysis module
- evaluation追加
- nontrivial API
- pipeline変更
- reusable functionality

Design / Knowledge Gateを原則要求。

scientific evidenceを生む場合Evidence Gateも要求。

---

## HIGH

例：

- model architecture
- objective/loss
- data/label definition
- central research hypothesis
- conclusion-critical analysis
- major metric semantic change
- expensive experiment

Design / Evidence / Knowledge Gateを要求。

semantic deviation時にはDeviation Gate必須。

---

# 20. LOCをRisk判定に使わない

5000行のboilerplateより、10行のlabel definition変更の方が高riskになり得る。

判定軸：

```text
research impact
interpretation impact
experimental validity
irreversibility
scope
cost
future recoverability
```

---

# 21. GitHub Object Model

## Research Question Issue

長期的研究問い。

例：

```text
[RQ] When and where does chirality information emerge?
```

---

## Work Issue

一つのconceptual work unit。

kind：

```text
experiment
analysis
implementation
bug
refactor
infrastructure
migration
```

Issue本文先頭にmachine markerを持たせる。

```html
<!-- rh:work {"schema":1,"kind":"experiment","risk":"high","evidence_required":true} -->
```

---

# 22. One PR ≈ One Conceptual Unit

PRサイズをLOCで制限しない。

原則：

> **研究者が一つの目的・仕組みとして説明可能な範囲を一つのPRにする。**

---

# 23. PR Semantics

Draft PRをimplementation ledgerとして使用する。

PR body：

```text
Linked Work
Purpose
Behavioral Change
Important Implementation
Key Design Decisions
Deviations
Validation
Evidence
Interpretation
Does NOT Establish
Known Limitations
Follow-up
Understanding Gate
```

---

# 24. Issue Close Semantics

## Implementation work

mergeによって目的が完了するなら、

```text
Closes #123
```

を使用可能。

## Experiment / Analysis

implementation PR mergeだけではcloseしない。

原則、

```text
Refs #123
```

とし、Result Record + Evidence Gate後にclose可能とする。

---

# 25. Durable Records

canonical durable recordsは、

> **Work Issue comments**

とする。

以下をrecordとして使用する。

```text
checkpoint
decision
result
gate
```

PR commentをcanonical record storeにしない。

---

# 26. Machine Marker

各recordのcomment先頭：

```html
<!-- rh:record {"schema":1,"kind":"checkpoint","id":"UUID","issue":184,"head":"abcdef1234","created_at":"..."} -->
```

Machine parserはmarkerを読む。

Markdown本文はhuman-readable representation。

---

# 27. Checkpoint Record

目的：

> 新規Agent sessionが作業状態を復元するためのminimum sufficient state。

本文：

```text
## Research Harness Checkpoint

### Done

### Current State

### Important Decisions

### Deviations

### Evidence Obtained

### Unexpected Findings

### Blocked By

### Remaining

### Next Action

### Provenance
- branch
- HEAD
- relevant run/artifact
```

作業日記にしてはならない。

---

# 28. Checkpoint Trigger

MUST：

```text
meaningful work session終了
Agent切替前
長時間experiment開始前
長時間experiment完了後
major deviation後
work interruption時
```

SHOULD：

```text
context compaction直前
大規模implementation完了時
```

MUST NOT：

```text
commitごと
functionごと
```

---

# 29. Decision Record

Human Gate Bで重要な変更を記録する。

```text
Trigger
Original Plan
Proposed Change
Options
Research Impact
Decision
Rationale
```

status：

```text
accepted
rejected
deferred
```

Current Intentは、

```text
Original Work Issue
+
accepted Decision Records
```

として解釈する。

元Issue本文を変更し続けてhistorical intentを消してはならない。

---

# 30. Result Record

```text
Question
Run / Evidence
Observation
Primary Metrics
Interpretation
Supports
Does NOT Support
Confounders
Unexpected Findings
Follow-up

Provenance:
- commit SHA
- configuration
- dataset/version
- seed
- run ID
- artifact path/URL
```

raw logsそのものをGitHubへ保存しない。

---

# 31. Gate Record

```text
gate:
  design
  deviation
  evidence
  knowledge

outcome:
  passed
  repaired
  overridden
  blocked
```

本文：

```text
Validated Concepts
Misconceptions Repaired
Unresolved
Outcome
```

Grill全文は保存しない。

---

# 32. State Model

derived state：

```text
UNTRACKED
SCOPED
DESIGN_GATE
READY
IN_PROGRESS
DEVIATION_GATE
BLOCKED
VALIDATING
EVIDENCE_GATE
KNOWLEDGE_GATE
READY_TO_MERGE
DONE
DEFERRED
ABANDONED
```

専用state databaseは作らない。

StateはGit + GitHub objects + durable recordsから計算する。

---

# 33. CLI Contract

distribution / target双方で同一logical CLIを使用する。

主要command：

```text
rh version
rh doctor
rh audit
rh adopt
rh upgrade

rh context
rh status

rh issue create
rh work start
rh work link

rh record checkpoint
rh record decision
rh record result
rh record gate

rh ready
rh sync
```

---

# 34. Structured Output

read / state commandは、

```text
--json
```

をMUST support。

mutation commandは可能な限り、

```text
--dry-run
```

をMUST support。

Exit code：

```text
0    success
!=0  failure / unmet precondition
```

---

# 35. `rh context --json`

最低限：

```json
{
  "repo_root": "...",
  "repo": "owner/name",
  "branch": "...",
  "head": "...",
  "dirty": true,
  "changed_paths": [],
  "remote": "origin",
  "pr": 185,
  "issue": 184,
  "harness_version": "0.1.0",
  "outbox_pending": 0
}
```

Skillの多くは最初にこれを利用する。

---

# 36. `rh status`

表示：

```text
Current Work
Derived State
Risk
Issue
PR
Branch
HEAD
Latest Checkpoint
Changes Since Checkpoint
Pending Gates
Blockers
Next Recorded Action
```

---

# 37. `rh work start ISSUE`

precondition：

```text
valid Work Issue
required Design Gate exists or override exists
git repo valid
GitHub remote valid
unsafe dirty operation不要
```

default branch：

```text
rh/<issue-number>-<slug>
```

ただし既存branch adoptionをsupportする。

```text
rh work start 184 --existing-branch probe-analysis
```

既存branchをrenameしてはならない。

処理：

```text
branch create/link
push
Draft PR create
initial PR body
```

---

# 38. Dirty Worktree Safety

RDHは自動で以下を実行してはならない。

```text
git reset --hard
git clean
git checkout -- .
automatic stash
```

既存dirty worktreeを破壊しない。

---

# 39. Destructive Operations

RDHは自動で以下を実行してはならない。

```text
gh pr merge
git push --force
git push --force-with-lease
branch delete
issue delete
history rewrite
release publication
```

`READY_TO_MERGE`がRDHの終端である。

mergeはRDH外で研究者が実行する。

---

# 40. Shell Safety

Git / GitHub CLIは、

```python
subprocess.run([...], shell=False)
```

相当で実行する。

Issue/PR/comment bodyはtemporary file + `--body-file`方式をSHOULD use。

GitHub上のtextをshell commandとして解釈してはならない。

---

# 41. Resume Workflow

`rh-resume` Skillは最重要機能とする。

読み込み順：

```text
1. rh context
2. Work Issue
3. accepted Decision Records
4. Result Records
5. latest Checkpoint
6. PR
7. Git changes since checkpoint
8. tests / CI information
```

出力：

```text
WHY

WHAT

CURRENT STATE

DONE

IMPORTANT DECISIONS

KNOWN EVIDENCE

LIMITATIONS

UNRESOLVED

NEXT
```

会話履歴がなくても復元できなければならない。

---

# 42. State Divergence

例えば、

```text
Issue says A
Decision says A
Checkpoint says A
Code implements B
```

ならAgentは、

```text
STATE DIVERGENCE DETECTED
```

として扱う。

Agentは、

```text
undocumented implementation drift
intentional but undocumented change
stale checkpoint
```

を評価する。

研究上重要ならDeviation Gateへ移る。

---

# 43. Agent Interruption Policy

Agentは次の場合に研究者へ介入を要求する。

```text
research intent changes
experimental validity changes
data/label semantics change
metric meaning changes
scope materially expands
major persistent architecture changes
significant experiment cost changes
unexpected evidence changes interpretation
explicit Human Gate reached
```

それ以外は原則として自律続行する。

---

# 44. Routine Decisions

以下では原則質問しない。

```text
function name
class layout
typing
fixtures
minor file organization
routine refactoring
normal error handling
logging
lint
serialization plumbing
test boilerplate
```

Human-in-every-loopにしてはならない。

---

# 45. Skills Architecture

Skillはthin orchestration adapterとする。

例：`rh-resume/SKILL.md`

概念的には、

```text
1. Locate repo root.
2. Run repo-local `rh context --json`.
3. Read `.research-harness/workflows/resume.md`.
4. Retrieve durable work state.
5. Reconstruct the semantic briefing.
6. Do not rely on chat history when durable state exists.
7. Do not modify research code until resume is complete.
```

程度。

長大なworkflow全文をClaude版/Codex版双方へ複製してはならない。

---

# 46. AGENTS.md / CLAUDE.md

既存fileを丸ごと管理しない。

RDH管理部分だけをmarkerで挿入する。

```text
<!-- BEGIN RESEARCH-HARNESS -->

...

<!-- END RESEARCH-HARNESS -->
```

既存内容はblock外で完全保持する。

---

# 47. Managed Instruction Minimum

内容：

```text
This repository uses Research Development Harness.

Use repository-local Harness state rather than chat history
to reconstruct tracked work.

For medium/high-impact new work, scope it before implementation.

Do not interrupt the researcher for routine implementation details.

Interrupt when research intent, validity, semantic definitions,
major architecture, significant scope/cost, evidence interpretation,
or explicit Human Gates require a human decision.

Record meaningful checkpoints.

Do not equate implementation completion with scientific conclusion.

Never auto-merge, force-push, rewrite history, or destroy user work.
```

詳細workflowをAGENTS.md / CLAUDE.mdへ全部埋め込まない。

---

# 48. Adoption of Existing Repositories

既存repoは、

> **Overlay + Cutover**

で導入する。

過去を再構成し直してはいけない。

---

# 49. `rh audit`

`rh audit`はread-onlyでなければならない。

最低限調査：

```text
repository root
git status
current branch
branches
worktrees
recent commits
remote
AGENTS.md
CLAUDE.md
.claude/
.agents/
.codex/
open Issues
open PRs
test infrastructure
likely experiment directories
likely result directories
```

semantic classificationはAgentが行う。

---

# 50. Adoption Agent Workflow

Agentはaudit結果とrepo内容から、

```text
Current research objectives
Active work candidates
Deferred work candidates
Likely abandoned work
Important historical decisions
Important evidence
Repository architecture
Known cognitive debt
Immediate next actions
```

をreconstructする。

ただしこれは推定値である。

---

# 51. Migration Human Gate

研究者が、

```text
active
deferred
abandoned
priority
incorrect inference
important missing result
```

を訂正する。

Agentの推測だけで既存workをabandoned等に確定してはならない。

---

# 52. Migration Baseline

adoption時に、

```text
.research-harness/baseline.md
```

を生成する。

内容：

```text
Cutover Date
Current Research Objectives
Active Work
Deferred Work
Abandoned Work
Important Historical Decisions
Important Existing Evidence
Repository Architecture
Known Cognitive Debt
Immediate Next Work
```

これはcutover snapshotであり、通常更新しない。

---

# 53. Historical Reconstruction Limit

禁止：

```text
past 100 commitsを全部Issue化
全branchのrename
過去実験を全部Result Recordへ変換
過去の会話・設計を完全復元
```

Migrationの目的は、

> 過去を完璧に整理することではなく、今日から迷子にならないこと。

---

# 54. Adoption File Safety

adoptionは既存research source fileを変更してはならない。

変更可能範囲：

```text
.research-harness/**
.claude/skills/rh-*/**
.agents/skills/rh-*/**
AGENTS.md managed block
CLAUDE.md managed block
```

`.github/`への変更はv0.1 defaultでは不要とする。

Issue/PR bodyはRDH内部templateから生成する。

---

# 55. `$HOME` Zero-Touch Acceptance

`adopt` / `upgrade` / project runtime commandの実行によって、

Harnessが`$HOME`以下にファイルを作成・変更してはならない。

テストではtemporary HOMEを指定し、

```text
before HOME tree
after HOME tree
```

がRDH起因で変化していないことを検証する。

これは必須acceptance testとする。

---

# 56. Offline / GitHub Failure

repository-local runtime stateは、

```text
.git/research-harness/
```

へ保存可能。

例：

```text
.git/research-harness/
├── outbox/
├── cache/
└── lock/
```

これはcommitしない。

---

# 57. Outbox

GitHub record writeに失敗した場合、

```text
.git/research-harness/outbox/<record-uuid>.json
```

へ保存する。

`rh sync`で再送する。

同一UUIDのrecordがremoteに存在する場合、再投稿しない。

retryはidempotentでなければならない。

---

# 58. Concurrency

原則：

> **One active writer per branch.**

並列Agent作業は、

```text
Work A → branch A
Work B → branch B
```

に分ける。

同じbranchをClaude/Codexが同時writeするworkflowを推奨してはならない。

---

# 59. Versioning

最低限分離する。

```text
runtime_version
bundle_version
record_schema_version
```

`manifest.toml`例：

```toml
schema_version = 1
bundle_version = "0.1.0"
runtime_version = "0.1.0"

[compatibility]
min_runtime_version = "0.1.0"
```

---

# 60. Upgrade Model

upgradeもglobal installerを使わない。

Harness distribution repositoryから、

```bash
./bin/rh upgrade /path/to/research-project
```

を行う。

対象repository自身がnetworkから最新版を取得するself-update機能はv0.1では不要。

---

# 61. Upgrade Safety

`upgrade --dry-run`を提供する。

表示：

```text
current version
target version
files to update
project modifications
managed block changes
conflicts
```

AGENTS.md / CLAUDE.mdはmanaged blockのみ更新。

過去GitHub recordを書き換えてschema migrationしてはならない。

Readerがold schemaをsupportする。

---

# 62. `rh doctor`

最低限確認：

```text
Python version
git available
gh available
gh authentication status
Git repository
GitHub remote
manifest
runtime compatibility
Claude adapters
Codex adapters
managed instruction blocks
record parsing
outbox
current branch linkage
current tracked work
```

severity：

```text
ERROR
WARNING
INFO
```

---

# 63. Distribution Repository Testing

## Unit

必須：

```text
config parsing
manifest parsing
record marker parser
record serialization
state inference
gate requirement logic
managed block merge
version comparison
outbox idempotency
```

---

## Git Integration

temporary Git repositoryで：

```text
dirty tree preserved
branch creation
existing branch adoption
HEAD detection
worktree handling
no reset
no stash
no history rewrite
```

---

## GitHub Integration

`gh` execution layerをmock/fake executableへ差し替え可能にする。

確認：

```text
issue create/read
comment records
Draft PR creation
PR read/update
pagination
auth failure
network failure
retry
duplicate UUID prevention
```

real GitHub accessをdefault CIで要求しない。

---

# 64. Mandatory Acceptance Scenarios

## A. Fresh repository

```text
adopt
→ RDH files installed
→ source unchanged
→ doctor passes
```

---

## B. Existing dirty repository

```text
existing AGENTS.md
existing CLAUDE.md
dirty research files
multiple branches
```

に対してadoptしても、

```text
dirty changes preserved
history preserved
existing docs outside managed block preserved
```

される。

---

## C. Existing project migration

Agent audit → researcher correction → baseline → active work adoption

が可能。

---

## D. Medium new work

```text
scope
→ Issue
→ Design Gate
→ work start
→ Draft PR
```

が成立。

---

## E. Agent switch

Claudeがcheckpointを残し、

翌日Codexがchat historyなしで、

```text
WHY
CURRENT
DECISIONS
EVIDENCE
NEXT
```

を復元できる。

逆方向も同様。

---

## F. Significant deviation

Agentが勝手にscopeを変更せず、

```text
Deviation Gate
→ researcher decision
→ Decision Record
```

となる。

---

## G. Negative experiment

仮説が支持されなくても、

```text
Experiment completed
Result recorded
Hypothesis not supported
```

として正常完了可能。

---

## H. Knowledge Gate

研究者が主要概念を説明できない場合、

READY_TO_MERGEにならない。

repair → restatement → passed後にready。

---

## I. Offline record

GitHub unreachable → outbox → `rh sync`

でexactly once相当のrecordが生成される。

---

## J. Zero-touch HOME

全integration/E2E testで、

> RDH自身は `$HOME` へ一切永続ファイルを書かない。

---

# 65. Implementation Phases

## Phase 0 — Scaffold

```text
distribution repo structure
Python package
bin/rh
command runner abstraction
tests
```

---

## Phase 1 — Local Core

```text
repository discovery
Git context
manifest/config
markers
records
state
managed blocks
doctor basics
```

---

## Phase 2 — Adoption

```text
audit
bundle generation/copy
target runtime
AGENTS/CLAUDE managed block
zero-touch HOME tests
existing repo safety tests
```

---

## Phase 3 — GitHub Adapter

```text
gh wrapper
repo resolution
Issue
PR
comments
pagination
auth/error handling
outbox
```

---

## Phase 4 — Work Lifecycle

```text
issue create
work start/link
context
status
record commands
ready
sync
```

---

## Phase 5 — Agent Workflows / Skills

```text
rh-scope
rh-start
rh-checkpoint
rh-resume
rh-status
rh-decision
rh-result
rh-finish
```

Claude / Codex adaptersを作成。

---

## Phase 6 — Human Gates

workflow documentsに、

```text
Design
Deviation
Evidence
Knowledge
```

を実装。

semantic logicはSkill側。

---

## Phase 7 — Upgrade / Hardening

```text
upgrade
schema compatibility
concurrency warning
doctor expansion
optional live E2E
```

---

# 66. Initial Harness Development

RDH自身の最初の実装時は、

```text
research-development-harness/
```

repositoryをRDHへself-adoptしてはならない。

まず通常のGit開発としてv0.1 coreを完成させる。

最低限のadoption / work lifecycleが動作するようになった後、

> RDH repository自身をRDHへadoptするdogfooding

をMAY performする。

これは後段のE2E validationとして扱う。

---

# 67. Current Platform Assumptions

実装時には必ず最新official documentationを再確認すること。

現行前提：

```text
Codex project skills:
    .agents/skills/

Claude Code project skills:
    .claude/skills/

Codex project instructions:
    AGENTS.md

GitHub:
    gh CLI
```

RDHはuser/global Skillを必要としない。

---

# 68. MUST NOT

実装Agentは以下を行ってはならない。

```text
$HOMEへのRDH install
global Python package必須化
global Claude/Codex Skill配置
巨大な単一Skill
独自server database
automatic merge
automatic force-push
automatic stash/reset
user source modification during adopt
historical Git rewrite
Grill全文保存
chain-of-thought保存
GitHubをraw log storage化
semantic research judgementのCLI実装
```

---

# 69. Design Priority

仕様にない細部では次の優先順位を使用する。

```text
1. User work / historyを破壊しない
2. $HOMEを汚さない
3. Research intentを失わない
4. Fresh sessionからrecoverできる
5. Claude/Codexで同一stateを共有できる
6. Deterministic部分をtest可能にする
7. GitHub recordを簡潔に保つ
8. Agentを不必要に止めない
9. Harnessを複雑にしすぎない
```

---

# 70. Definition of Done

v0.1の最低完成条件：

```text
1. Harness distribution repoからtarget repoへadoptできる。

2. Target repoはadopt後、distribution repoやglobal installなしで
   repo-local rhを実行できる。

3. $HOMEへRDH固有fileを一切作らない。

4. Existing dirty repoを破壊せずadoptできる。

5. Claude/Codex双方のproject-local Skillが配置される。

6. Issue → Design Gate → Draft PR → Checkpoint
   のworkflowが機能する。

7. Fresh Agent sessionからresumeできる。

8. Decision / Result / Gate RecordをIssue commentとして永続化できる。

9. READY_TO_MERGEまで到達できる。

10. Harness自身はmergeしない。

11. GitHub failure時にrecordをoutboxへ退避し、
    後でidempotentにsyncできる。

12. 上記の主要behaviorがautomated testで検証されている。
```

---

# 71. Final Contract

Research Development Harnessは、

> **Git + GitHub + repository-local workflowを研究者の外部記憶として利用し、Claude Code / Codexを高速な実装主体として動かしながら、Intent、Major Deviation、Evidence Interpretation、Final UnderstandingだけをHuman Gateとして保持する。**

RDHはAI codingを遅くするためのシステムではない。

AIによる大量の進捗が、

> 「何を、なぜ、どうやって、どこまでやり、何が分かったのか分からない」

というcognitive debtへ変換されることを防ぐシステムである。

その研究状態は、

```text
Git
+
Work Issue
+
Decision Records
+
Result Records
+
Checkpoints
+
Gate Records
```

から新しいAgent sessionでも復元可能でなければならない。

そしてRDH自身は、

> **完全repository-localかつ非破壊的であること**

を最上位のdeployment contractとする。