# Vision Grounding Agent

Vision grounding is an alternative perception layer for the Browser-Use agent that replaces the default DOM-based element indexing with screenshot-derived bounding-box detection. Instead of a numbered `[index]` element list, the agent receives labeled visual annotations on the screenshot and interacts exclusively through normalized viewport coordinates.

---

## Table of Contents

- [Vision Grounding Agent](#vision-grounding-agent)
  - [Table of Contents](#table-of-contents)
  - [Why Vision Grounding?](#why-vision-grounding)
  - [Architecture Overview](#architecture-overview)
  - [Modes](#modes)
  - [Quick Start](#quick-start)
  - [Python API](#python-api)
    - [Agent Parameters](#agent-parameters)
    - [Full Example](#full-example)
      - [Fallback mode — only activates on DOM-empty pages](#fallback-mode--only-activates-on-dom-empty-pages)
  - [CLI](#cli)
    - [CLI Parameters](#cli-parameters)
    - [CLI Examples](#cli-examples)
  - [How It Works Step by Step](#how-it-works-step-by-step)
  - [Coordinate System](#coordinate-system)
  - [Tool Changes in Vision Mode](#tool-changes-in-vision-mode)
  - [System Prompt Differences](#system-prompt-differences)
  - [Choosing a Grounding Model](#choosing-a-grounding-model)
  - [VisionGroundingService API](#visiongroundingservice-api)
    - [`ground_elements(screenshot_b64, task_context) → VisionGroundingResult`](#ground_elementsscreenshot_b64-task_context--visiongroundingresult)
    - [`build_elements_description(result) → str`](#build_elements_descriptionresult--str)
    - [`create_grounded_screenshot(screenshot_b64, result) → str`](#create_grounded_screenshotscreenshot_b64-result--str)
  - [Data Models](#data-models)
    - [`VisionGroundingResult`](#visiongroundingresult)
    - [`GroundedElement`](#groundedelement)
    - [`BoundingBox`](#boundingbox)
  - [Limitations](#limitations)

---

## Why Vision Grounding?

The default agent relies on a DOM accessibility tree to enumerate interactive elements. This works well on standard HTML pages but has several blind spots:

- **Canvas / SVG UI** — elements rendered purely in graphics have no DOM nodes.
- **Shadow DOM / Web Components** — deeply nested or closed shadow roots are invisible to standard DOM traversal.
- **Third-party embeds** — cross-origin iframes, PDF viewers, and video players expose no DOM.
- **Heavily styled single-page apps** — many React/Vue apps produce a DOM tree that doesn't map cleanly to what is visually clickable.

Vision grounding solves these cases by asking a multimodal LLM to look at a screenshot and identify the interactive elements the agent currently needs, producing pixel-accurate bounding boxes regardless of the underlying DOM structure.

---

## Architecture Overview

```
Agent.run()
    │
    ├─ capture screenshot via DOMWatchdog
    │
    ├─ _maybe_apply_vision_grounding(BrowserStateSummary)
    │       │
    │       └─ VisionGroundingService.ground_elements(screenshot_b64, task)
    │               │
    │               └─ grounding LLM  →  VisionGroundingResult
    │                       │
    │                       └─ [GroundedElement(label, bbox, element_type), ...]
    │
    ├─ annotated screenshot drawn with labeled bounding boxes
    │
    └─ BrowserStateSummary updated:
            vision_grounding_active = True
            vision_grounding_elements_description  (text for the LLM prompt)
            vision_grounding_elements              (list of GroundedElement)
            vision_grounding_instruction           (coordinate-action directions)
```

When vision grounding is active, the **agent LLM** receives:

1. An annotated screenshot with colored, labeled boxes drawn over interactive elements.
2. A text list of those elements with their center coordinates in normalized 0–1000 space.
3. A dedicated system prompt that instructs coordinate-only interaction.

---

## Modes

| `use_vision_grounding` | Behavior |
|---|---|
| `False` (default) | Disabled. Standard DOM-based element indexing. |
| `True` | Always active. Every step uses vision grounding; DOM indices are never exposed to the agent LLM. |
| `'fallback'` | Activates only when the DOM selector map is empty (e.g. canvas pages, iframes with zero DOM nodes). Falls back gracefully to DOM mode when elements are detected normally. |

---

## Quick Start

```python
import asyncio
from browser_use import Agent, ChatBrowserUse

async def main():
    llm = ChatBrowserUse()
    agent = Agent(
        task="Go to https://example.com and click the 'More information...' link",
        llm=llm,
        use_vision_grounding=True,      # always-on vision mode
    )
    history = await agent.run()
    print(history.final_result())

asyncio.run(main())
```

A separate grounding model is optional — by default the same LLM is used for both agent reasoning and element detection.

---

## Python API

### Agent Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `use_vision_grounding` | `bool \| Literal['fallback']` | `False` | Enable vision grounding mode. |
| `vision_grounding_llm` | `BaseChatModel \| None` | `None` | Separate multimodal LLM to use for element detection. Falls back to the main `llm` when `None`. |
| `use_vision` | `bool \| Literal['auto']` | `True` | Must not be `False` when vision grounding is enabled; grounding requires screenshots. |

> `use_vision_grounding` is independent of `use_vision`. Setting `use_vision_grounding=True` while `use_vision=False` will suppress the annotated screenshot from the agent's context, which defeats the purpose. Both should be enabled together (the default `use_vision=True` is correct).

### Full Example

```python
import asyncio
from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI

async def main():
    # Use a dedicated grounding model (must support vision / image input)
    grounding_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.0)
    agent_llm = ChatBrowserUse()

    browser = Browser(headless=False)

    agent = Agent(
        task="Fill in the rental inquiry form",
        llm=agent_llm,
        browser=browser,
        use_vision=True,
        use_vision_grounding=True,          # always-on
        vision_grounding_llm=grounding_llm, # dedicated model for element detection
        max_actions_per_step=3,
    )

    history = await agent.run(max_steps=20)
    print(history.final_result())

asyncio.run(main())
```

#### Fallback mode — only activates on DOM-empty pages

```python
agent = Agent(
    task="Interact with the canvas dashboard",
    llm=llm,
    use_vision_grounding='fallback',  # kicks in only when DOM is sparse
)
```

---

## CLI

A standalone CLI is provided for manual testing, accessible as a Python module:

```bash
python -m browser_use.vision_grounding.cli "YOUR TASK HERE" [OPTIONS]
```

### CLI Parameters

| Argument | Default | Description |
|---|---|---|
| `task` (positional) | `"Open https://example.com and describe the visible interactive elements."` | The task for the agent. |
| `--provider` | `google` | LLM provider: `browser-use`, `openai`, `google`, or `anthropic`. |
| `--model` | Provider default | Override the default model name. |
| `--mode` | `vision` | Grounding mode: `vision` (always-on), `fallback`, or `off`. |
| `--headless` | off | Run the browser without a visible window. |
| `--max-steps` | `12` | Maximum agent steps. |
| `--max-actions-per-step` | `3` | Maximum actions emitted per step. |
| `--user-data-dir` | None | Path to a Chrome profile directory (preserves cookies/logins). |
| `--keep-alive` | off | Keep the browser open after the run finishes. |
| `--allowed-domain` | None | Restrict navigation to a domain pattern. Repeat to allow multiple. |

Provider defaults:

| Provider | Default Model |
|---|---|
| `browser-use` | `bu-latest` |
| `openai` | `gpt-5` |
| `google` | `gemini-3-pro-preview` |
| `anthropic` | `claude-sonnet-4-5` |

### CLI Examples

```bash
# Always-on vision mode with the Google provider
export GOOGLE_API_KEY=your_key
python -m browser_use.vision_grounding.cli \
  "Open https://example.com and describe the interactive elements" \
  --provider google \
  --mode vision

# Fallback mode with OpenAI, headless, 20 steps
export OPENAI_API_KEY=your_key
python -m browser_use.vision_grounding.cli \
  "Search for 'browser automation' on DuckDuckGo" \
  --provider openai \
  --model gpt-4.1-mini \
  --mode fallback \
  --headless \
  --max-steps 20

# Keep the browser alive after the run for inspection
python -m browser_use.vision_grounding.cli \
  "Fill the contact form on https://example.com" \
  --provider browser-use \
  --keep-alive

# Restrict to a single domain
python -m browser_use.vision_grounding.cli \
  "Find the pricing page" \
  --provider anthropic \
  --allowed-domain "*.example.com"
```

---

## How It Works Step by Step

1. **Screenshot capture** — at the start of each agent step, the `DOMWatchdog` captures a screenshot of the current viewport.

2. **`_maybe_apply_vision_grounding`** — called on the `BrowserStateSummary` before the agent LLM is invoked. It checks the active mode:
   - `True`: always proceeds to grounding.
   - `'fallback'`: proceeds only if `len(selector_map) == 0`.
   - `False`: skips entirely.

3. **Grounding call** — `VisionGroundingService.ground_elements(screenshot_b64, task)` sends the screenshot and a task-context prompt to the grounding LLM. The LLM returns a structured `VisionGroundingResult` with labeled bounding boxes in normalized 0–1000 coordinates.

4. **Screenshot annotation** — `create_grounded_screenshot` draws colored bounding boxes and short labels onto the screenshot using PIL. Buttons are drawn in coral (`#FF6B6B`); other interactive types in sky blue (`#45B7D1`).

5. **State update** — the annotated screenshot replaces the original in `BrowserStateSummary`. The element list and a coordinate-action instruction are attached as text fields.

6. **Tool mode switch** — `tools.set_vision_grounding_mode(True)` swaps the `click`, `input`, and `scroll` action schemas to accept `coordinate_x`/`coordinate_y` instead of DOM `index`. DOM-index-only actions (`dropdown_options`, `select_dropdown`, `upload_file`) are removed.

7. **Agent LLM step** — the agent sees the annotated screenshot, the element description list, and the coordinate-based system prompt. It emits actions with coordinates.

8. **Coordinate translation** — at execution time, the normalized 0–1000 coordinates are translated to actual viewport pixels by the tools layer before being sent via CDP.

9. **Error recovery** — if the grounding call raises an exception, a warning is logged and the agent continues with DOM-based context for that step (in `'fallback'` mode) or retries (with `use_vision_grounding=True`).

---

## Coordinate System

All bounding box coordinates use a **normalized 0–1000 range**:

- `0` = left or top edge of the viewport.
- `1000` = right or bottom edge of the viewport.

This is viewport-resolution-independent: coordinates are stable regardless of window size. At click/input execution time, the tools layer scales them to actual pixel coordinates using the current viewport dimensions.

```
Viewport (any resolution)
╔══════════════════════════════════╗
║ (0,0)                  (1000,0) ║
║                                 ║
║           center                ║
║          (500,500)               ║
║                                 ║
║ (0,1000)              (1000,1000)║
╚══════════════════════════════════╝
```

Example interaction (as emitted by the agent LLM):

```json
{"action": "click", "coordinate_x": 342, "coordinate_y": 178}
{"action": "input", "coordinate_x": 500, "coordinate_y": 300, "text": "hello world"}
```

---

## Tool Changes in Vision Mode

When `set_vision_grounding_mode(True)` is called, the Tools registry dynamically swaps action schemas:

| Tool | Standard mode | Vision grounding mode |
|---|---|---|
| `click` | requires `index: int` | requires `coordinate_x: int, coordinate_y: int` |
| `input` | requires `index: int` | requires `coordinate_x: int, coordinate_y: int` |
| `scroll` | requires `index: int` | requires `coordinate_x: int, coordinate_y: int` |
| `dropdown_options` | available | **removed** |
| `select_dropdown` | available | **removed** |
| `upload_file` | available | **removed** |

All other tools (`navigate`, `search`, `go_back`, `extract`, `screenshot`, `write_file`, etc.) remain unchanged.

In `'fallback'` mode the tool schema is reset to DOM mode at the start of each step and only switched to coordinate mode if grounding is actually triggered.

---

## System Prompt Differences

Vision grounding uses a dedicated system prompt (`system_prompt_vision_grounding.md`) instead of the default one.

The key differences:

- **No DOM index references** — `[index]<tagname attribute=value />` format is absent.
- **Coordinate-only interaction** — `click(coordinate_x=X, coordinate_y=Y)` and `input(coordinate_x=X, coordinate_y=Y, text="...")` are the primary interaction tools.
- **Screenshot is ground truth** — the agent is explicitly instructed to reason from the annotated screenshot first and use listed center coordinates.
- **Re-read after page changes** — the agent is told to check the new grounded element list after any navigation or interaction that changes the page.

---

## Choosing a Grounding Model

The grounding model must support **vision (image) input**. The agent reasoning model may be text-only if a separate `vision_grounding_llm` is provided.

Recommendations:

| Use case | Suggestion |
|---|---|
| Best accuracy | `ChatBrowserUse()` — built specifically for browser tasks |
| Cost-sensitive | `ChatGoogle(model="gemini-flash-latest")` |
| OpenAI stack | `ChatOpenAI(model="gpt-4.1-mini", temperature=0.0)` |
| Anthropic stack | `ChatAnthropic(model="claude-sonnet-4-5")` |

The grounding call uses `detail='high'` image input and requests structured JSON output matching `VisionGroundingResult`. Keep this in mind when estimating token costs — high-detail screenshots use significantly more tokens than low-detail ones.

---

## VisionGroundingService API

```python
from browser_use.vision_grounding import VisionGroundingService

service = VisionGroundingService(llm)
```

### `ground_elements(screenshot_b64, task_context) → VisionGroundingResult`

Sends the screenshot and task description to the grounding LLM. Returns a `VisionGroundingResult` containing the identified interactive elements with normalized 0–1000 bounding boxes.

- `screenshot_b64: str` — base64-encoded PNG screenshot.
- `task_context: str` — description of the current agent task (used to focus element selection).

### `build_elements_description(result) → str`

Formats the list of grounded elements into a human-readable string suitable for inclusion in the agent's LLM prompt. Returns a message indicating no elements were found if the list is empty.

### `create_grounded_screenshot(screenshot_b64, result) → str`

Draws colored bounding boxes and short labels onto the screenshot using PIL, then returns the annotated image as a new base64-encoded PNG. The original image is not modified.

---

## Data Models

### `VisionGroundingResult`

```python
class VisionGroundingResult(BaseModel):
    elements: list[GroundedElement]  # may be empty
```

### `GroundedElement`

```python
class GroundedElement(BaseModel):
    label: str        # short unique tag rendered on the screenshot, e.g. "A1" or "SEARCH_BUTTON"
    bbox: BoundingBox
    element_type: str | None  # approximate type: "button", "input", "link", "dropdown", "checkbox", …
```

### `BoundingBox`

```python
class BoundingBox(BaseModel):
    x: int      # left edge, normalized 0–1000
    y: int      # top edge, normalized 0–1000
    width: int  # element width, normalized 0–1000
    height: int # element height, normalized 0–1000

    @property
    def center_x(self) -> int: ...
    @property
    def center_y(self) -> int: ...
```

---

## Limitations

- **Requires a vision-capable LLM.** The grounding call fails if the model does not support image input.
- **Extra latency per step.** Each step makes an additional LLM call for element detection. On high-detail screenshots this can be 2–5× more expensive than a text-only DOM step.
- **No file upload in vision mode.** `upload_file` is removed from the tool registry when vision grounding is active; use DOM mode for tasks that require file inputs.
- **Dropdown selection.** `select_dropdown` is removed in vision mode. Use `click` on the dropdown and then `click` on the desired option by coordinate instead.
- **Dynamic / animated pages.** If the page changes between the grounding call and action execution (e.g. an overlay appears), coordinates may no longer be accurate. The agent is instructed to re-read the new grounded element list after page changes.
- **Scrolled-off content.** Only elements visible in the current viewport are grounded. Use `scroll` and re-trigger grounding on the next step to reach off-screen elements.
