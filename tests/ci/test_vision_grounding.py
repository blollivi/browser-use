import base64
import io
from typing import Any, cast

from PIL import Image

from browser_use import Agent
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt
from browser_use.browser.views import BrowserStateSummary
from browser_use.tools.service import Tools
from browser_use.vision_grounding.service import VisionGroundingService
from tests.ci.conftest import create_mock_llm


class DummyDOMState:
	def __init__(self, selector_map: dict[int, object] | None = None, text: str = 'DOM elements'):
		self.selector_map = selector_map or {}
		self._root = None
		self._text = text

	def llm_representation(self, include_attributes=None) -> str:
		return self._text


def _make_test_screenshot() -> str:
	image = Image.new('RGBA', (64, 48), color=(255, 255, 255, 255))
	buffer = io.BytesIO()
	image.save(buffer, format='PNG')
	image.close()
	return base64.b64encode(buffer.getvalue()).decode('utf-8')


async def test_vision_grounding_service_returns_elements_and_annotated_screenshot():
	grounding_llm = create_mock_llm(
		actions=[
			'{"elements": [{"label": "A1", "bbox": {"x": 8, "y": 6, "width": 20, "height": 12}, "element_type": "button"}]}'
		]
	)
	service = VisionGroundingService(grounding_llm)
	screenshot_b64 = _make_test_screenshot()

	result = await service.ground_elements(screenshot_b64, task_context='Click the main button')

	assert len(result.elements) == 1
	assert result.elements[0].label == 'A1'
	assert 'center=(18, 12)' in service.build_elements_description(result)

	annotated_screenshot_b64 = await service.create_grounded_screenshot(screenshot_b64, result)

	assert annotated_screenshot_b64 != screenshot_b64


async def test_agent_applies_vision_grounding_in_fallback_mode():
	main_llm = create_mock_llm()
	grounding_llm = create_mock_llm(
		actions=[
			'{"elements": [{"label": "SEARCH", "bbox": {"x": 10, "y": 8, "width": 24, "height": 14}, "element_type": "input"}]}'
		]
	)
	agent = Agent(
		task='Fill the search field',
		llm=main_llm,
		use_vision_grounding='fallback',
		vision_grounding_llm=grounding_llm,
	)
	state = BrowserStateSummary(
		dom_state=cast(Any, DummyDOMState(selector_map={})),
		url='https://example.com',
		title='Example',
		tabs=[],
		screenshot=_make_test_screenshot(),
	)

	await agent._maybe_apply_vision_grounding(state)

	assert state.vision_grounding_active is True
	assert 'Task-relevant interactive elements' in (state.vision_grounding_elements_description or '')
	assert len(state.vision_grounding_elements) == 1


def test_agent_message_prompt_prefers_vision_grounded_elements():
	state = BrowserStateSummary(
		dom_state=cast(Any, DummyDOMState(selector_map={1: object()}, text='DOM fallback text')),
		url='https://example.com',
		title='Example',
		tabs=[],
		screenshot=_make_test_screenshot(),
		vision_grounding_active=True,
		vision_grounding_elements_description='Task-relevant interactive elements:\n[A1] <button> center=(2, 4)',
		vision_grounding_instruction='Use coordinate-based actions with the listed center coordinates.',
	)

	message = AgentMessagePrompt(
		browser_state_summary=state,
		file_system=cast(Any, None),
		task='Click the grounded button',
		screenshots=[state.screenshot] if state.screenshot else [],
	).get_user_message(use_vision=True)

	assert 'Task-relevant interactive elements' in message.text
	assert 'DOM fallback text' not in message.text
	assert '<vision_grounding_mode>' not in message.text
	assert '0 links, 0 interactive' not in message.text


def test_system_prompt_uses_dedicated_vision_template():
	prompt = SystemPrompt(max_actions_per_step=3, use_vision_grounding=True).get_system_message().content

	assert '[index]<tagname attribute=value />' not in prompt
	assert 'Only interact with elements that have a numeric [index] assigned.' not in prompt
	assert 'Use coordinate-based interaction for visible UI controls' in prompt
	assert 'The screenshot with labels is the source of truth' in prompt


def test_tools_switch_to_coordinate_only_models_in_vision_mode():
	tools = Tools()
	tools.set_vision_grounding_mode(True)

	click_fields = tools.registry.registry.actions['click'].param_model.model_fields
	input_fields = tools.registry.registry.actions['input'].param_model.model_fields
	scroll_fields = tools.registry.registry.actions['scroll'].param_model.model_fields

	assert 'index' not in click_fields
	assert 'index' not in input_fields
	assert 'index' not in scroll_fields
	assert 'coordinate_x' in click_fields
	assert 'coordinate_y' in click_fields
	assert 'coordinate_x' in input_fields
	assert 'coordinate_y' in input_fields
	assert 'dropdown_options' not in tools.registry.registry.actions
	assert 'select_dropdown' not in tools.registry.registry.actions
	assert 'upload_file' not in tools.registry.registry.actions


async def test_agent_enables_coordinate_only_tools_in_vision_only_mode():
	main_llm = create_mock_llm()
	grounding_llm = create_mock_llm(
		actions=[
			'{"elements": [{"label": "SEARCH", "bbox": {"x": 10, "y": 8, "width": 24, "height": 14}, "element_type": "input"}]}'
		]
	)
	agent = Agent(
		task='Fill the search field',
		llm=main_llm,
		use_vision_grounding=True,
		vision_grounding_llm=grounding_llm,
	)

	assert 'index' not in agent.tools.registry.registry.actions['click'].param_model.model_fields
	assert 'index' not in agent.tools.registry.registry.actions['input'].param_model.model_fields
	assert 'dropdown_options' not in agent.tools.registry.registry.actions