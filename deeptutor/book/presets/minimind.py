"""Preset interactive book for learning MiniMind's LLM training pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookDepth,
    BookInputs,
    BookProposal,
    BookStatus,
    Chapter,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ContentType,
    Page,
    PageStatus,
    Progress,
    SourceAnchor,
    Spine,
)
from deeptutor.book.storage import BookStorage
from deeptutor.services.path_service import PathService

BOOK_ID = "bk_minimind_interactive"
PRESET_REVISION = 1
_SOURCE = "https://github.com/jingyaogong/minimind"


@dataclass(frozen=True, slots=True)
class _PageSpec:
    chapter_id: str
    page_id: str
    title: str
    summary: str
    objectives: tuple[str, ...]
    body: str
    key_idea: str
    widget_title: str
    widget: str
    questions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _ChapterSpec:
    id: str
    title: str
    summary: str
    objectives: tuple[str, ...]
    content_type: ContentType
    prerequisites: tuple[str, ...]


_CHAPTERS: tuple[_ChapterSpec, ...] = (
    _ChapterSpec(
        id="ch_pipeline",
        title="MiniMind 全景路线",
        summary="把 MiniMind 的训练链路拆成可逐步验证的学习地图。",
        objectives=(
            "说明 MiniMind 适合解决的学习问题",
            "区分预训练、SFT、偏好优化和推理部署",
            "制定不依赖高端 GPU 的学习路线",
        ),
        content_type=ContentType.OVERVIEW,
        prerequisites=(),
    ),
    _ChapterSpec(
        id="ch_tokenizer",
        title="Tokenizer 与训练数据",
        summary="理解文本如何变成 token 序列，以及数据格式如何影响后续训练。",
        objectives=(
            "解释 BPE 与 Byte-Level BPE 的基本差异",
            "追踪一条文本从字符串到 token id 的转换",
            "识别词表大小对 embedding 参数量的影响",
        ),
        content_type=ContentType.CONCEPT,
        prerequisites=("ch_pipeline",),
    ),
    _ChapterSpec(
        id="ch_transformer",
        title="Transformer 与注意力",
        summary="从张量形状和因果掩码两个视角理解 MiniMind 的模型主干。",
        objectives=(
            "描述 causal attention 对下一个 token 预测的约束",
            "解释 RoPE 如何编码相对位置",
            "说明 KV cache 为什么能加速自回归生成",
        ),
        content_type=ContentType.THEORY,
        prerequisites=("ch_tokenizer",),
    ),
    _ChapterSpec(
        id="ch_train",
        title="Pretrain 与 SFT",
        summary="比较 next-token prediction 与对话模板掩码这两种学习信号。",
        objectives=(
            "写出 causal LM loss 的输入和目标错位关系",
            "解释 SFT 只训练 assistant 回复的原因",
            "区分 pretrain_t2t 与 sft_t2t 数据格式",
        ),
        content_type=ContentType.DERIVATION,
        prerequisites=("ch_transformer",),
    ),
    _ChapterSpec(
        id="ch_lora",
        title="LoRA 与偏好优化",
        summary="理解参数高效微调、DPO、PPO 和 GRPO 各自解决的问题。",
        objectives=(
            "说明 LoRA 低秩分解减少可训练参数的机制",
            "比较 DPO 与 RL 目标的使用场景",
            "解释 reward model、policy 和 rollout 的关系",
        ),
        content_type=ContentType.THEORY,
        prerequisites=("ch_train",),
    ),
    _ChapterSpec(
        id="ch_deploy",
        title="推理、评测与实验路线",
        summary="把训练产物接到推理服务，并用可控实验验证每个改进。",
        objectives=(
            "比较 Transformers、llama.cpp、vLLM 和 Ollama 的定位",
            "设计一组低算力可完成的 MiniMind 实验",
            "避免把格式对齐误读为知识能力提升",
        ),
        content_type=ContentType.PRACTICE,
        prerequisites=("ch_lora",),
    ),
)


def _widget(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }}
body {{ margin: 0; padding: 16px; background: #f7f8fb; color: #172033; font-size: 14px; }}
@media (prefers-color-scheme: dark) {{ body {{ background: #10151f; color: #eef2f8; }} }}
h2 {{ margin: 0 0 4px; font-size: 17px; letter-spacing: 0; }}
p.meta {{ margin: 0 0 14px; color: #667085; font-size: 12px; }}
.grid {{ display: grid; gap: 12px; }}
.row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
button {{ border: 1px solid #cfd6e4; background: white; color: inherit; border-radius: 6px; padding: 6px 9px; font: inherit; cursor: pointer; }}
button[aria-pressed=true] {{ border-color: #2563eb; background: #e8efff; color: #1747c2; }}
.card {{ background: white; border: 1px solid #dce2ee; border-radius: 8px; padding: 12px; }}
@media (prefers-color-scheme: dark) {{ .card, button {{ background: #182131; border-color: #303b4f; }} button[aria-pressed=true] {{ background: #182c53; color: #a8c4ff; }} }}
input[type=text], textarea, select {{ min-width: 160px; width: 100%; box-sizing: border-box; border: 1px solid #cfd6e4; background: white; color: inherit; border-radius: 6px; padding: 7px 8px; font: inherit; }}
textarea {{ min-height: 76px; resize: vertical; }}
input[type=range] {{ width: 180px; accent-color: #2563eb; }}
.stage {{ min-height: 76px; }}
.tokens {{ display: flex; flex-wrap: wrap; gap: 5px; }}
.token {{ border: 1px solid #cfd6e4; background: #eef2f8; border-radius: 5px; padding: 3px 5px; font-family: ui-monospace, monospace; font-size: 12px; }}
.token.id {{ background: transparent; border-style: dashed; color: #667085; }}
.mask {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(40px, 1fr)); gap: 5px; }}
.cell {{ border-radius: 5px; border: 1px solid #cfd6e4; aspect-ratio: 1; display: grid; place-items: center; font-size: 11px; }}
.on {{ background: #dcfce7; border-color: #86bd96; }}
.off {{ background: #f1f3f7; color: #98a2b3; }}
@media (prefers-color-scheme: dark) {{ .token {{ background: #202b3d; }} .token.id {{ color: #98a2b3; }} .on {{ background: #153725; border-color: #28794b; }} .off {{ background: #172131; }} }}
.stat {{ font-family: ui-monospace, monospace; font-size: 18px; font-weight: 700; }}
.muted {{ color: #667085; font-size: 12px; }}
.answer {{ margin-top: 10px; border-top: 1px dashed #cfd6e4; padding-top: 10px; }}
ul {{ margin: 8px 0 0; padding-left: 20px; }}
li {{ margin: 4px 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def _pipeline_widget() -> str:
    return _widget(
        "训练管线学习地图",
        """
<h2>MiniMind 训练管线</h2>
<p class="meta">点击阶段查看输入、输出和第一个可验证检查。</p>
<div class="row" id="nav"></div>
<div class="card stage" id="stage"></div>
<script>
const stages = [
  {name:"数据与分词", input:"jsonl / text / conversations", output:"token id + loss mask", check:"统计同一句话的 token 长度"},
  {name:"模型结构", input:"[batch, seq, hidden]", output:"logits [batch, seq, vocab]", check:"打印 causal mask 形状"},
  {name:"预训练", input:"pretrain_t2t", output:"base checkpoint", check:"确认 next-token shift 正确"},
  {name:"SFT", input:"sft_t2t conversations", output:"chat checkpoint", check:"只让 assistant 回复计入 loss"},
  {name:"LoRA / 偏好", input:"adapter data / chosen-rejected", output:"adapter or aligned model", check:"冻结参数量与可训练参数量"},
  {name:"推理评测", input:"checkpoint + prompts", output:"生成文本 / metrics", check:"使用无交集固定测试集"}
];
const nav=document.getElementById("nav"), stage=document.getElementById("stage");
let current=0;
function render(){nav.innerHTML="";stages.forEach((s,i)=>{const b=document.createElement("button");b.textContent=(i+1)+". "+s.name;b.setAttribute("aria-pressed",i===current);b.onclick=()=>{current=i;render()};nav.appendChild(b)});const s=stages[current];stage.innerHTML=`<strong>${s.name}</strong><div class="row" style="margin-top:8px"><span>输入：${s.input}</span></div><div class="row"><span>输出：${s.output}</span></div><div class="answer">第一个检查：${s.check}</div>`;}
render();
</script>""",
    )


def _tokenizer_widget() -> str:
    return _widget(
        "Tokenizer 观察器",
        """
<h2>从文本到 token id</h2>
<p class="meta">这是一个教学模拟：用近似切分展示词表大小如何影响序列长度与 embedding 参数。</p>
<textarea id="text">Transformer 通过自注意力理解上下文。</textarea>
<div class="row" style="margin-top:10px">
<label><input type="radio" name="vocab" value="6400" checked> 小词表 6,400</label>
<label><input type="radio" name="vocab" value="32000"> 大词表 32,000</label>
<button id="run" type="button">重新编码</button>
</div>
<div class="card" style="margin-top:12px"><div class="tokens" id="tokens"></div>
<div class="row" style="margin-top:10px"><span>token 数：<b id="count">0</b></span><span>embedding+输出参数：<b id="params">0</b></span></div>
<p class="muted">参数按词表 × 768 × 2 粗略估算，只用于感受量级。</p></div>
<script>
const text=document.getElementById("text"),out=document.getElementById("tokens");
function split(t,large){const parts=[];for(const item of t.match(/[A-Za-z]+|[0-9]+|\\s+|./g)||[]){if(/[A-Za-z]/.test(item)){if(large&&item.length>4)parts.push(item.slice(0,Math.ceil(item.length/2)),item.slice(Math.ceil(item.length/2)));else parts.push(item)}else if(/[\\u4e00-\\u9fff]/.test(item)){if(!large)parts.push(item,item);else parts.push(item)}else parts.push(item)}return parts.filter(x=>x.trim().length)}
function render(){const large=document.querySelector('input[value="32000"]').checked,vocab=large?32000:6400,parts=split(text.value,large);out.innerHTML="";parts.forEach((p,i)=>{const s=document.createElement("span");s.className="token";s.textContent=p;out.appendChild(s);const id=document.createElement("span");id.className="token id";let h=17;for(const c of p)h=(h*131+c.codePointAt(0))%vocab;id.textContent=h;out.appendChild(id)});document.getElementById("count").textContent=parts.length;document.getElementById("params").textContent=(vocab*768*2).toLocaleString()}
document.getElementById("run").onclick=render;for(const r of document.querySelectorAll('input[name=vocab]'))r.onclick=render;render();
</script>""",
    )


def _attention_widget() -> str:
    return _widget(
        "因果注意力矩阵",
        """
<h2>Causal Attention 可视化</h2>
<p class="meta">拖动 query 位置，绿色格子表示当前 token 可以注意的历史 token。</p>
<input id="text" type="text" value="The model predicts the next token">
<div class="row" style="margin-top:10px"><span>Query 位置</span><input id="pos" type="range" min="0" value="4"><b id="label"></b></div>
<div class="card" style="margin-top:12px"><div id="tokens" class="tokens"></div><div class="mask" id="mask" style="margin-top:10px"></div>
<p class="muted">每列是 key，绿色代表允许注意；未来位置永远被 mask 掉。</p></div>
<script>
const input=document.getElementById("text"),range=document.getElementById("pos"),mask=document.getElementById("mask"),tokens=document.getElementById("tokens"),label=document.getElementById("label");
function tokensOf(t){return (t.match(/[A-Za-z]+|./g)||[]).filter(x=>x.trim())}
function render(){const ts=tokensOf(input.value);range.max=Math.max(0,ts.length-1);range.value=Math.min(range.value,range.max);const q=+range.value;label.textContent=q+1+" / "+ts.length;tokens.innerHTML="";ts.forEach((t,i)=>{const s=document.createElement("span");s.className="token";s.style.borderColor=i===q?"#2563eb":"";s.textContent=t;tokens.appendChild(s)});mask.innerHTML="";ts.forEach((t,i)=>{const c=document.createElement("div");c.className="cell "+(i<=q?"on":"off");c.textContent=i<=q?"✓":"×";c.title="key "+(i+1)+": "+t;mask.appendChild(c)})}
range.oninput=render;input.oninput=render;render();
</script>""",
    )


def _training_widget() -> str:
    return _widget(
        "训练目标与掩码实验",
        """
<h2>损失掩码</h2>
<p class="meta">同一个对话模板，在预训练与 SFT 下哪些位置提供梯度并不相同。</p>
<div class="row"><button id="pre" aria-pressed="true">Pretrain</button><button id="sft" aria-pressed="false">SFT</button><button id="dpo" aria-pressed="false">DPO</button></div>
<div class="card" style="margin-top:12px"><div class="tokens" id="tokens"></div><div class="answer" id="note"></div></div>
<script>
const items=[["system","你是有用助手",false],["user","解释注意力",false],["assistant","注意力加权价值",true],["tool","返回检索结果",false],["chosen","更清楚的解释",true],["rejected","冗长且跑题",false]];
const modes={pre:{label:"预训练：所有普通文本位置都可以预测下一个 token",use:i=>i<4},sft:{label:"SFT：主要训练 assistant 回复 token",use:i=>i<4&&items[i][2]},dpo:{label:"DPO：比较 chosen 与 rejected 的相对概率",use:i=>i>=4}};
let mode="pre";
function render(){for(const k of ["pre","sft","dpo"])document.getElementById(k).setAttribute("aria-pressed",k===mode);const box=document.getElementById("tokens");box.innerHTML="";items.forEach((x,i)=>{if(mode==="dpo"&&i<4)return;const s=document.createElement("span");s.className="token";s.textContent=x[0]+":"+x[1];s.className="token "+(modes[mode].use(i)?"on":"off");box.appendChild(s)});document.getElementById("note").textContent=modes[mode].label}
for(const k of ["pre","sft","dpo"])document.getElementById(k).onclick=()=>{mode=k;render()};render();
</script>""",
    )


def _lora_widget() -> str:
    return _widget(
        "LoRA 秩与偏好信号",
        """
<h2>低秩更新的代价</h2>
<p class="meta">原矩阵 512×512 被冻结，只训练 A/B 两个低秩矩阵。</p>
<div class="row"><span>rank r</span><input id="rank" type="range" min="1" max="64" value="8"><b id="r"></b></div>
<div class="card" style="margin-top:12px"><div class="stat" id="params"></div><div id="formula" class="muted"></div>
<div class="answer"><strong>偏好目标</strong><div class="row" style="margin-top:6px"><button data-goal="dpo" aria-pressed="true">DPO</button><button data-goal="ppo" aria-pressed="false">PPO</button><button data-goal="grpo" aria-pressed="false">GRPO</button></div><p id="goal"></p></div></div>
<script>
const rank=document.getElementById("rank");
const goals={dpo:"离线 chosen/rejected 对，直接放大偏好概率差，适合先做稳定对齐实验。",ppo:"需要 reward 反馈、value/critic 和策略约束，训练链路更重。",grpo:"同一 prompt 生成一组 rollout，用组内相对表现作为 baseline，适合可自动比较的任务。"};
function render(){const r=+rank.value;document.getElementById("r").textContent=r;document.getElementById("params").textContent=(r*512*2).toLocaleString()+" / 262,144";document.getElementById("formula").textContent=`可训练比例约 ${(r*2/512*100).toFixed(1)}%；前向：Wx + BAx`}
rank.oninput=render;let goal="dpo";function renderGoal(){for(const b of document.querySelectorAll("[data-goal]"))b.setAttribute("aria-pressed",b.dataset.goal===goal);document.getElementById("goal").textContent=goals[goal]}for(const b of document.querySelectorAll("[data-goal]"))b.onclick=()=>{goal=b.dataset.goal;renderGoal()};render();renderGoal();
</script>""",
    )


def _experiment_widget() -> str:
    return _widget(
        "实验路线生成器",
        """
<h2>生成低算力实验计划</h2>
<p class="meta">选择当前条件，得到下一步能实际执行的检查。</p>
<div class="row"><label><input type="checkbox" checked> 只读代码</label><label><input type="checkbox"> 有 mini 数据</label><label><input type="checkbox"> 有 GPU</label><label><input type="checkbox"> 要做评测</label></div>
<div class="card" style="margin-top:12px"><ul id="plan"></ul></div>
<script>
function render(){const checked=[...document.querySelectorAll("input[type=checkbox]")].map(x=>x.checked);const plan=["把 MiniMind clone 到独立目录，记录 commit 和 requirements。"];if(checked[0])plan.push("阅读 model_minimind.py，逐层打印输入输出形状。");if(checked[1])plan.push("取 100 条 mini 数据，检查 conversations 字段和特殊 token。");if(checked[2])plan.push("用极小 batch 跑 10 step，记录 loss、显存和耗时。");else plan.push("在 CPU/MPS 上做 tokenizer 与 mask 单元实验，不承诺完整训练。");if(checked[3])plan.push("建立 20 条固定 prompt 和无交集测试集，保存每次输出。");plan.push("每次只改一个变量，并把结果写入实验日志。");document.getElementById("plan").innerHTML=plan.map(x=>`<li>${x}</li>`).join("")}
for(const x of document.querySelectorAll("input[type=checkbox]"))x.onchange=render;render();
</script>""",
    )

_PAGES: tuple[_PageSpec, ...] = (
    _PageSpec(
        chapter_id="ch_pipeline",
        page_id="pg_pipeline",
        title="MiniMind 全景路线",
        summary="用一张训练地图回答：现在该读代码、跑数据，还是先理解算法。",
        objectives=(
            "说明 MiniMind 适合解决的学习问题",
            "区分预训练、SFT、偏好优化和推理部署",
            "制定不依赖高端 GPU 的学习路线",
        ),
        body=(
            "MiniMind 的价值不在于 64M 参数能打败商用模型，而在于它把 LLM 的核心链路"
            "压缩到一个人可以读完、跑通、逐步修改的规模。学习它时，先把管线分成六段："
            "数据与分词、模型结构、预训练、SFT、参数高效与偏好优化、推理评测。\n\n"
            "推荐的第一轮不要追求完整训练。先下载已训练模型跑推理，确认 tokenizer、chat template "
            "和 generate 循环能连起来；再读 `model_minimind.py` 中的 attention、RoPE 和 MoE；"
            "最后用 mini 数据做短 epoch，把 loss、显存和输出质量的变化记录下来。\n\n"
            "算力预期也要现实：README 的 2 小时 SFT 基准来自 RTX 3090。Mac 的 MPS 可以做小批量"
            "教学实验，但完整复现训练会慢得多；这类设备更适合读代码、做单元张量实验和运行小模型推理。"
        ),
        key_idea=(
            "把 MiniMind 当作可验证的 LLM 核心实验台：每个阶段只回答一个问题，"
            "并用一小段数据或一个张量检查证明自己理解了。"
        ),
        widget_title="训练管线学习地图",
        widget=_pipeline_widget(),
        questions=(
            {
                "question_id": "q_pipeline_stage",
                "question": "MiniMind 中 SFT 的主要学习信号是什么？",
                "question_type": "choice",
                "options": {
                    "A": "任意网页文本的下一个 token",
                    "B": "对话模板中 assistant 回复位置的 token",
                    "C": "人工偏好中 chosen 与 rejected 的相对概率",
                    "D": "推理引擎返回的缓存 key",
                },
                "correct_answer": "B",
                "explanation": "SFT 使用带角色标记的对话数据，并通过 mask 把主要损失放在 assistant 回复上。",
                "difficulty": "basic",
            },
            {
                "question_id": "q_pipeline_device",
                "question": "在没有 NVIDIA GPU 的 Mac 上，比较合理的第一步是什么？",
                "question_type": "choice",
                "options": {
                    "A": "直接完整预训练并等待数天",
                    "B": "先跑推理、读模型代码并做小规模张量实验",
                    "C": "跳过 tokenizer，因为词表不影响模型",
                    "D": "只看 benchmark，不阅读训练代码",
                },
                "correct_answer": "B",
                "explanation": "Mac/MPS 适合教学验证，完整复现训练应租用合适 GPU 或使用已发布模型。",
                "difficulty": "basic",
            },
        ),
    ),
    _PageSpec(
        chapter_id="ch_lora",
        page_id="pg_lora",
        title="LoRA 与偏好优化",
        summary="从“怎么微调便宜”走到“怎么让模型更符合偏好”。",
        objectives=(
            "说明 LoRA 低秩分解减少可训练参数的机制",
            "比较 DPO 与 RL 目标的使用场景",
            "解释 reward model、policy 和 rollout 的关系",
        ),
        body=(
            "LoRA 不直接更新大矩阵 `W`，而是学习 `BA`，其中 `B` 和 `A` 的秩远小于原矩阵维度。"
            "前向计算变成 `Wx + BAx`，原权重可冻结，可训练参数大幅减少；合并后仍能得到一个普通矩阵。\n\n"
            "DPO 用 chosen/rejected 回复对直接优化偏好概率差，不需要在线采样和独立 reward model。"
            "它实现简单、稳定，适合先建立偏好对齐直觉。PPO 则需要 reward 信号、value 学习和策略约束；"
            "GRPO 用组内相对比较简化 critic 部分，适合可自动判分或多 rollout 对比的场景。\n\n"
            "读 MiniMind 的 RLAIF/Agentic RL 代码时，先画出三个对象：policy 负责生成，rollout engine "
            "提供样本，reward 或规则评价样本。再看 advantage、clip、group baseline 和 tool-use 轨迹"
            "分别改变哪些梯度。"
        ),
        key_idea=(
            "LoRA 降低参数更新成本；DPO/PPO/GRPO 改变优化目标。前者是“怎么训”，后者是“训成什么样”。"
        ),
        widget_title="LoRA 秩与偏好信号",
        widget=_lora_widget(),
        questions=(
            {
                "question_id": "q_lora_params",
                "question": "LoRA 降低可训练参数量的核心做法是什么？",
                "question_type": "choice",
                "options": {
                    "A": "删除 attention 层",
                    "B": "用两个低秩矩阵的乘积表示权重增量",
                    "C": "把所有权重压缩成 int8",
                    "D": "只训练 tokenizer",
                },
                "correct_answer": "B",
                "explanation": "冻结原权重，训练低秩 `A/B` 增量，推理前可合并回原矩阵。",
                "difficulty": "basic",
            },
            {
                "question_id": "q_lora_dpo",
                "question": "DPO 与 PPO 最典型的输入差异是什么？",
                "question_type": "choice",
                "options": {
                    "A": "DPO 使用 chosen/rejected 偏好对，PPO 常使用 reward 加策略采样",
                    "B": "DPO 只能用于图像，PPO 只能用于文本",
                    "C": "DPO 不需要 tokenizer，PPO 需要",
                    "D": "PPO 不更新模型参数",
                },
                "correct_answer": "A",
                "explanation": "DPO 直接从偏好对推导目标；PPO 通常需要 reward 反馈和在线 rollout。",
                "difficulty": "intermediate",
            },
        ),
    ),
    _PageSpec(
        chapter_id="ch_deploy",
        page_id="pg_deploy",
        title="推理、评测与实验路线",
        summary="把“跑起来”和“有效果”分开验证，实验才可信。",
        objectives=(
            "比较 Transformers、llama.cpp、vLLM 和 Ollama 的定位",
            "设计一组低算力可完成的 MiniMind 实验",
            "避免把格式对齐误读为知识能力提升",
        ),
        body=(
            "Transformers 格式适合教学、转换和轻量推理；llama.cpp/Ollama 便于本地部署；vLLM 更偏服务端"
            "吞吐。MiniMind 还提供 OpenAI-compatible API 示例，可以把 reasoning、tool call 等字段接到"
            "自己的客户端里测试。\n\n"
            "低算力实验可以先做四类：tokenizer 长度统计、attention mask 形状检查、小步 SFT loss 曲线、"
            "固定 prompt 的生成对比。每次只改一个变量，并保存数据、代码、权重名和随机种子。\n\n"
            "评测时要看清信号来源。MiniMind 的 benchmark 说明中特别提醒：小模型很容易通过格式对齐在"
            "选择题上提升，甚至污染数据下出现虚高分数。真正有价值的结论应来自无交集测试集、多组 prompt "
            "和稳定指标。"
        ),
        key_idea=(
            "部署解决可访问性，评测证明变化有效；不要把“输出格式更像考试”误判成“知识能力更强”。"
        ),
        widget_title="实验路线生成器",
        widget=_experiment_widget(),
        questions=(
            {
                "question_id": "q_deploy_engine",
                "question": "更偏服务端高吞吐推理的选项通常是哪一个？",
                "question_type": "choice",
                "options": {
                    "A": "vLLM",
                    "B": "Tokenizer 训练脚本",
                    "C": "Dataset 下载目录",
                    "D": "RoPE scaling 配置",
                },
                "correct_answer": "A",
                "explanation": "vLLM 面向服务化推理吞吐；llama.cpp/Ollama 更偏本地轻量部署。",
                "difficulty": "basic",
            },
            {
                "question_id": "q_deploy_eval",
                "question": "如何降低小模型评测虚高的风险？",
                "question_type": "choice",
                "options": {
                    "A": "使用与训练/格式对齐无交集的测试集并固定多组 prompt",
                    "B": "只测试训练集中出现过的题目",
                    "C": "只比较生成文本长度",
                    "D": "每次同时修改模型、数据、学习率和模板",
                },
                "correct_answer": "A",
                "explanation": "无交集测试与稳定重复测量更能区分知识能力和格式对齐效果。",
                "difficulty": "intermediate",
            },
        ),
    ),
    _PageSpec(
        chapter_id="ch_transformer",
        page_id="pg_transformer",
        title="Transformer 与注意力",
        summary="看懂形状和掩码，比先背公式更能读懂模型代码。",
        objectives=(
            "描述 causal attention 对下一个 token 预测的约束",
            "解释 RoPE 如何编码相对位置",
            "说明 KV cache 为什么能加速自回归生成",
        ),
        body=(
            "自注意力的输入通常记作 `[batch, seq_len, hidden]`。Q、K、V 投影后，attention score "
            "是 query 和 key 的相似度，softmax 后用来加权 value。Transformer block 还包含 FFN、"
            "residual connection 和 normalization；读懂每一步形状变化，代码就不再神秘。\n\n"
            "解码器使用因果掩码：第 `i` 个位置只能看到 `<= i` 的 key。训练时模型能在一个序列里并行"
            "预测多个条件概率，但生成时仍只能从左到右逐 token 输出。\n\n"
            "RoPE 把 query 和 key 旋转到二维子空间，使内积主要依赖相对位置。KV cache 则把历史 token "
            "的 key/value 保存下来；每生成一个新 token，只需要计算新 query 与已有 K/V 的注意力，"
            "避免重复编码整段上下文。MoE 版本进一步把 FFN 替换成多个专家和路由，让每个 token "
            "只激活一部分参数。"
        ),
        key_idea=(
            "因果掩码保证训练目标合法；RoPE 表达相对位置；KV cache 把重复上下文计算变成历史缓存查询。"
        ),
        widget_title="因果注意力矩阵",
        widget=_attention_widget(),
        questions=(
            {
                "question_id": "q_attention_mask",
                "question": "causal mask 的直接作用是什么？",
                "question_type": "choice",
                "options": {
                    "A": "让每个位置只能注意自己和之前的 token",
                    "B": "删除所有位置编码",
                    "C": "把模型改成双向编码器",
                    "D": "阻止模型使用 KV cache",
                },
                "correct_answer": "A",
                "explanation": "因果掩码把未来位置的注意力分数屏蔽，保证下一个 token 预测不泄漏答案。",
                "difficulty": "basic",
            },
            {
                "question_id": "q_attention_cache",
                "question": "自回归生成时 KV cache 主要节省了什么？",
                "question_type": "choice",
                "options": {
                    "A": "不再需要 tokenizer",
                    "B": "不必每步重算历史 token 的 key/value",
                    "C": "让 loss 不需要 softmax",
                    "D": "把所有专家合并成一个 FFN",
                },
                "correct_answer": "B",
                "explanation": "历史 K/V 可缓存复用，新 step 只处理新增 query 与必要的新投影。",
                "difficulty": "intermediate",
            },
        ),
    ),
    _PageSpec(
        chapter_id="ch_train",
        page_id="pg_train",
        title="Pretrain 与 SFT",
        summary="同一个交叉熵，不同的数据组织和损失掩码，会得到很不同的能力。",
        objectives=(
            "写出 causal LM loss 的输入和目标错位关系",
            "解释 SFT 只训练 assistant 回复的原因",
            "区分 pretrain_t2t 与 sft_t2t 数据格式",
        ),
        body=(
            "预训练的目标是 next-token prediction。若输入是 `x[:, :-1]`，目标就是 `x[:, 1:]`；"
            "模型在位置 `i` 根据前文预测第 `i+1` 个 token。交叉熵只惩罚目标 token 的负对数概率，"
            "但它对整个序列并行执行。\n\n"
            "SFT 数据包含 system、user、assistant、tool 等角色。训练时通常把 prompt 和特殊控制 token "
            "之外的损失 mask 掉，只在 assistant 内容位置计算 loss，让模型学习在给定指令下如何回应。\n\n"
            "MiniMind 的新版 SFT 数据还混入 tool call 和 `<think>` 标记。这里要区分能力来源：数据模板"
            "让模型学会何时输出某种格式，真正能否推理和调用工具仍取决于模型容量、数据质量与训练覆盖面。"
        ),
        key_idea=(
            "预训练学条件分布，SFT 学角色与响应格式；数据 mask 决定哪些位置提供梯度。"
        ),
        widget_title="训练目标与掩码实验",
        widget=_training_widget(),
        questions=(
            {
                "question_id": "q_train_shift",
                "question": "causal LM 训练中 logits 的预测目标通常如何构造？",
                "question_type": "choice",
                "options": {
                    "A": "用同一位置完全相同的 token 作为标签",
                    "B": "用右移一位的下一个 token 作为标签",
                    "C": "用句向量分类结果作为标签",
                    "D": "用随机替换后的 token 作为标签",
                },
                "correct_answer": "B",
                "explanation": "输入 `x[:, :-1]` 预测 `x[:, 1:]`，实现每个位置的前文到下一 token 条件概率。",
                "difficulty": "basic",
            },
            {
                "question_id": "q_train_sft_mask",
                "question": "SFT 中只保留 assistant 回复位置损失的主要理由是什么？",
                "question_type": "choice",
                "options": {
                    "A": "减少 batch 大小",
                    "B": "让模型学习响应给定指令，而不是复述用户 prompt",
                    "C": "避免使用 tokenizer",
                    "D": "让训练完全不需要 GPU",
                },
                "correct_answer": "B",
                "explanation": "用户输入是条件，不是希望模型逐字生成的内容；mask 让梯度集中在目标回复上。",
                "difficulty": "intermediate",
            },
        ),
    ),
    _PageSpec(
        chapter_id="ch_tokenizer",
        page_id="pg_tokenizer",
        title="Tokenizer 与训练数据",
        summary="字符串不是模型的输入；token id 序列才是。",
        objectives=(
            "解释 BPE 与 Byte-Level BPE 的基本差异",
            "追踪一条文本从字符串到 token id 的转换",
            "识别词表大小对 embedding 参数量的影响",
        ),
        body=(
            "Tokenizer 负责两端转换：训练前把文本切成词表里的 id，生成后把 id 解回文本。"
            "BPE 从字符或字节开始，反复合并高频相邻单元；Byte-Level BPE 进一步保证任何字节序列"
            "都能表示，避免遇到未见字符就彻底失败。\n\n"
            "MiniMind 使用约 6,400 的小词表。这会让中文和英文混排文本的序列更长，但 embedding "
            "与输出投影的参数显著减少。对 64M 级模型来说，这是学习成本和模型体积之间很务实的取舍。\n\n"
            "预训练数据 `pretrain_t2t` 的核心字段是 `text`；SFT 数据 `sft_t2t` 则保存 `conversations`，"
            "并可携带 tools、tool_calls、think 等特殊模板标记。你修改 tokenizer 或模板时，旧权重和新数据"
            "不再共享同一套 id 映射，评估结果也会失去可比性。"
        ),
        key_idea=(
            "词表不是小事：它同时决定序列长度、特殊能力标记、embedding 参数量和跨版本可比性。"
        ),
        widget_title="Tokenizer 观察器",
        widget=_tokenizer_widget(),
        questions=(
            {
                "question_id": "q_tokenizer_vocab",
                "question": "小词表的主要代价是什么？",
                "question_type": "choice",
                "options": {
                    "A": "同样文本通常需要更多 token 表示",
                    "B": "模型不能再使用 attention",
                    "C": "所有中文都会变成未知字符",
                    "D": "loss 必须从交叉熵改为 MSE",
                },
                "correct_answer": "A",
                "explanation": "小词表节省 embedding 参数，但编码效率通常下降，同一段文本会占更多 token。",
                "difficulty": "basic",
            },
            {
                "question_id": "q_tokenizer_template",
                "question": "为什么不建议随手重训 MiniMind tokenizer？",
                "question_type": "choice",
                "options": {
                    "A": "tokenizer 训练代码无法阅读",
                    "B": "词表和模板变化会破坏旧权重、数据和生态兼容",
                    "C": "新 tokenizer 不能编码英文",
                    "D": "GPU 不支持 embedding 查表",
                },
                "correct_answer": "B",
                "explanation": "token id 映射一旦变化，旧权重、旧数据格式和第三方推理转换都需要重新对齐。",
                "difficulty": "intermediate",
            },
        ),
    ),
)


def _anchor() -> SourceAnchor:
    return SourceAnchor(
        kind="web",
        ref=_SOURCE,
        snippet="MiniMind: Train a Tiny LLM from Scratch",
    )


def _block(
    block_id: str,
    block_type: BlockType,
    title: str,
    params: dict[str, Any],
    payload: dict[str, Any],
) -> Block:
    timestamp = 1_788_100_000.0
    return Block(
        id=block_id,
        type=block_type,
        status=BlockStatus.READY,
        title=title,
        params=params,
        payload=payload,
        source_anchors=[_anchor()],
        metadata={"preset": "minimind", "handcrafted": True},
        created_at=timestamp,
        updated_at=timestamp,
    )


def _page(spec: _PageSpec, order: int) -> Page:
    timestamp = 1_788_100_000.0
    page_id = spec.page_id
    return Page(
        id=page_id,
        book_id=BOOK_ID,
        chapter_id=spec.chapter_id,
        title=spec.title,
        learning_objectives=list(spec.objectives),
        content_type=ContentType.THEORY,
        status=PageStatus.READY,
        order=order,
        blocks=[
            _block(
                f"blk_{page_id}_text",
                BlockType.TEXT,
                "章节讲解",
                {"role": "explanation"},
                {"format": "markdown", "body": spec.body, "role": "explanation"},
            ),
            _block(
                f"blk_{page_id}_idea",
                BlockType.CALLOUT,
                "核心要点",
                {"variant": "key_idea"},
                {
                    "variant": "key_idea",
                    "label": "核心要点",
                    "body": spec.key_idea,
                },
            ),
            _block(
                f"blk_{page_id}_interactive",
                BlockType.INTERACTIVE,
                spec.widget_title,
                {"interaction": "walkthrough", "title": spec.widget_title},
                {
                    "description": spec.widget_title,
                    "chart_type": "interactive",
                    "code": {"language": "html", "content": spec.widget},
                },
            ),
            _block(
                f"blk_{page_id}_quiz",
                BlockType.QUIZ,
                "本章自测",
                {"num_questions": len(spec.questions), "difficulty": "basic"},
                {"questions": list(spec.questions), "topic": spec.title},
            ),
        ],
        created_at=timestamp,
        updated_at=timestamp,
    )


def _concept_graph() -> ConceptGraph:
    return ConceptGraph(
        nodes=[
            ConceptNode(id="pipeline", label="训练管线", chapter_id="ch_pipeline", description="LLM 从数据到部署的主路径", weight=1.3),
            ConceptNode(id="data", label="训练数据", chapter_id="ch_tokenizer", description="jsonl 文本与多轮对话格式"),
            ConceptNode(id="tokenizer", label="Tokenizer", chapter_id="ch_tokenizer", description="文本与 token id 的双向映射"),
            ConceptNode(id="attention", label="因果注意力", chapter_id="ch_transformer", description="屏蔽未来位置的自注意力"),
            ConceptNode(id="rope", label="RoPE", chapter_id="ch_transformer", description="相对位置编码"),
            ConceptNode(id="pretrain", label="预训练", chapter_id="ch_train", description="下一个 token 条件概率"),
            ConceptNode(id="sft", label="SFT", chapter_id="ch_train", description="指令对话微调与 loss mask"),
            ConceptNode(id="lora", label="LoRA", chapter_id="ch_lora", description="低秩参数高效微调"),
            ConceptNode(id="preference", label="偏好优化", chapter_id="ch_lora", description="DPO、PPO 与 GRPO"),
            ConceptNode(id="inference", label="推理部署", chapter_id="ch_deploy", description="Transformers、llama.cpp、vLLM、Ollama"),
            ConceptNode(id="evaluation", label="可信评测", chapter_id="ch_deploy", description="无交集测试与固定 prompt"),
        ],
        edges=[
            ConceptEdge(src="pipeline", dst="data"),
            ConceptEdge(src="data", dst="tokenizer"),
            ConceptEdge(src="tokenizer", dst="attention"),
            ConceptEdge(src="attention", dst="rope", relation="extends"),
            ConceptEdge(src="attention", dst="pretrain"),
            ConceptEdge(src="pretrain", dst="sft"),
            ConceptEdge(src="sft", dst="lora"),
            ConceptEdge(src="lora", dst="preference"),
            ConceptEdge(src="sft", dst="inference"),
            ConceptEdge(src="inference", dst="evaluation", relation="extends"),
        ],
    )


def _spine() -> Spine:
    timestamp = 1_788_100_000.0
    pages_by_chapter = {page.chapter_id: page.page_id for page in _PAGES}
    chapters = [
        Chapter(
            id=chapter.id,
            title=chapter.title,
            learning_objectives=list(chapter.objectives),
            content_type=chapter.content_type,
            source_anchors=[_anchor()],
            prerequisites=list(chapter.prerequisites),
            page_ids=[pages_by_chapter[chapter.id]],
            summary=chapter.summary,
            order=index,
        )
        for index, chapter in enumerate(_CHAPTERS, start=1)
    ]
    return Spine(
        book_id=BOOK_ID,
        chapters=chapters,
        version=1,
        updated_at=timestamp,
        concept_graph=_concept_graph(),
        exploration_summary="Hand-authored preset based on the public MiniMind repository and training pipeline.",
    )


def _book() -> Book:
    timestamp = 1_788_100_000.0
    return Book(
        id=BOOK_ID,
        revision=1,
        title="MiniMind 互动书：从 Tokenizer 到小模型训练",
        description="面向源码学习的中文互动书，用 6 个章节拆解 MiniMind 的分词、模型结构、预训练、SFT、LoRA、偏好优化、推理与评测。",
        status=BookStatus.READY,
        proposal=BookProposal(
            title="MiniMind 互动书：从 Tokenizer 到小模型训练",
            description="A Chinese interactive companion for learning the MiniMind tiny-LLM project.",
            scope="Cover the end-to-end MiniMind training path with source-reading experiments; exclude full GPU training operationally.",
            target_level="intermediate",
            estimated_chapters=len(_CHAPTERS),
            rationale="The preset uses DeepTutor's native reader, interactive blocks, concept graph, and quizzes so learners can inspect the model without setting up a full training run first.",
        ),
        knowledge_bases=[],
        language="zh",
        depth=BookDepth.BRIEF,
        page_count=len(_PAGES),
        chapter_count=len(_CHAPTERS),
        created_at=timestamp,
        updated_at=timestamp,
        metadata={
            "preset": "minimind",
            "preset_revision": PRESET_REVISION,
            "source": _SOURCE,
            "handcrafted": True,
            "block_types": ["text", "callout", "interactive", "quiz"],
        },
    )


def _inputs() -> BookInputs:
    return BookInputs(
        source_refs=[{"kind": "web", "ref": _SOURCE}],
        source_context=(
            "MiniMind is an Apache-2.0 educational project that trains a tiny LLM "
            "from scratch and covers tokenizer, pretraining, SFT, LoRA, DPO, RLAIF, "
            "tool use, inference, and evaluation."
        ),
        user_intent="Create a Chinese interactive DeepTutor book for learning MiniMind.",
        language="zh",
        captured_at=1_788_100_000.0,
    )


def build_minimind_book() -> tuple[Book, BookInputs, Spine, list[Page]]:
    """Build the preset without touching runtime storage."""

    chapter_order = {chapter.id: index for index, chapter in enumerate(_CHAPTERS)}
    pages = [
        _page(spec, order)
        for order, spec in enumerate(
            sorted(_PAGES, key=lambda page: chapter_order[page.chapter_id]),
            start=1,
        )
    ]
    return _book(), _inputs(), _spine(), pages


def install_minimind_book(
    storage: BookStorage,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Persist the preset. Re-running is a no-op unless ``force`` is set."""

    existing = storage.load_book(BOOK_ID)
    if existing is not None and not force:
        metadata = existing.metadata or {}
        if metadata.get("preset") != "minimind":
            raise ValueError(f"Book id {BOOK_ID} already belongs to a non-preset book")
        if int(metadata.get("preset_revision") or 0) >= PRESET_REVISION:
            return {"status": "already_installed", "book_id": BOOK_ID}

    if existing is not None and force:
        metadata = existing.metadata or {}
        if metadata.get("preset") != "minimind":
            raise ValueError(f"Refusing to overwrite non-preset book {BOOK_ID}")

    book, inputs, spine, pages = build_minimind_book()
    storage.save_book(book)
    storage.save_inputs(BOOK_ID, inputs)
    storage.save_spine(spine)
    for page in pages:
        storage.save_page(page)

    if storage.load_progress(BOOK_ID) is None:
        storage.save_progress(Progress(book_id=BOOK_ID, current_page_id=pages[0].id))
    storage.append_log(
        BOOK_ID,
        f"Installed MiniMind interactive book preset revision {PRESET_REVISION}"
        + (" (forced)" if force and existing is not None else ""),
        op="install",
    )
    return {"status": "installed", "book_id": BOOK_ID, "pages": len(pages)}


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        help="DeepTutor runtime workspace root (the directory containing data/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall this preset while preserving reader progress",
    )
    args = parser.parse_args()
    data_root = args.workspace_root / "data" if args.workspace_root else None
    storage = BookStorage(path_service=PathService(workspace_root=data_root))
    print(json.dumps(install_minimind_book(storage, force=args.force), ensure_ascii=False))


if __name__ == "__main__":
    _main()
