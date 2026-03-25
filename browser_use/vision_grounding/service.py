import base64
import io
import logging

from PIL import Image, ImageDraw

from browser_use.browser.python_highlights import draw_enhanced_bounding_box_with_text, get_cross_platform_font
from browser_use.llm.base import BaseChatModel
from browser_use.llm.messages import ContentPartImageParam, ContentPartTextParam, ImageURL, SystemMessage, UserMessage
from browser_use.vision_grounding.views import GroundedElement, VisionGroundingResult

logger = logging.getLogger(__name__)


_VISION_GROUNDING_SYSTEM_PROMPT = """You are a UI grounding model.

Identify ONLY the interactive elements that the agent needs to complete its current task.

Requirements:
- Return only elements directly relevant to the task described in the user message.
- Do NOT enumerate every interactive element on the page. Focus on what the agent needs right now.
- Include the minimal set: the target element(s) plus any navigation controls needed to reach them (e.g. a tab, a scroll region, a search box).
- Do not include decorative text, layout containers, or duplicated nested boxes for the same control.
- ALL bounding box coordinates (x, y, width, height) must be expressed in a normalized 0–1000 range,
  where 0 is the left/top edge and 1000 is the right/bottom edge of the screenshot.
- Labels must be short and unique so they can be rendered onto the screenshot.
"""


def _scale_grounding_result(result: VisionGroundingResult, img_w: int, img_h: int) -> VisionGroundingResult:
	"""Scale bounding box coordinates from normalized 0-1000 range to actual image pixel coordinates."""
	from browser_use.vision_grounding.views import BoundingBox, GroundedElement

	scaled_elements: list[GroundedElement] = []
	for elem in result.elements:
		b = elem.bbox
		scaled_elements.append(
			GroundedElement(
				label=elem.label,
				bbox=BoundingBox(
					x=round(b.x * img_w / 1000),
					y=round(b.y * img_h / 1000),
					width=max(1, round(b.width * img_w / 1000)),
					height=max(1, round(b.height * img_h / 1000)),
				),
				element_type=elem.element_type,
			)
		)
	return VisionGroundingResult(elements=scaled_elements)


class VisionGroundingService:
	def __init__(self, llm: BaseChatModel):
		self.llm = llm

	async def ground_elements(self, screenshot_b64: str, task_context: str) -> VisionGroundingResult:
		prompt = (
			f'Task: {task_context}\n\n'
			'Identify ONLY the interactive elements needed to complete this task and return their labels and bounding boxes. '
			'Include only the minimal set of elements the agent must interact with right now.'
		)

		response = await self.llm.ainvoke(
			[
				SystemMessage(content=_VISION_GROUNDING_SYSTEM_PROMPT),
				UserMessage(
					content=[
						ContentPartTextParam(text=prompt),
						ContentPartImageParam(
							image_url=ImageURL(
								url=f'data:image/png;base64,{screenshot_b64}',
								media_type='image/png',
								detail='high',
							)
						),
					]
				),
			],
			output_format=VisionGroundingResult,
		)

		result = response.completion
		if not isinstance(result, VisionGroundingResult):
			result = VisionGroundingResult.model_validate(result)

		# Keep coordinates in normalized 0-1000 space.
		# The agent LLM receives 0-1000 coords and returns them; conversion to
		# viewport pixels happens at click/input execution time.
		# Scaling to pixels only happens locally inside create_grounded_screenshot for drawing.

		return result

	def build_elements_description(self, result: VisionGroundingResult) -> str:
		if not result.elements:
			return 'No task-relevant elements were identified in the screenshot.'

		lines = [
			'Task-relevant interactive elements (coordinates are normalized 0–1000: 0=left/top, 1000=right/bottom):',
		]
		lines.extend(result.to_prompt_lines())
		return '\n'.join(lines)

	async def create_grounded_screenshot(self, screenshot_b64: str, result: VisionGroundingResult) -> str:
		if not result.elements:
			return screenshot_b64

		image = Image.open(io.BytesIO(base64.b64decode(screenshot_b64))).convert('RGBA')
		img_w, img_h = image.size
		draw = ImageDraw.Draw(image)
		font = get_cross_platform_font(12)

		try:
			for element in result.elements:
				# Scale 0-1000 normalized coords to pixel coords for drawing only
				scaled = _scale_grounding_result(VisionGroundingResult(elements=[element]), img_w, img_h).elements[0]
				self._draw_grounded_element(draw=draw, element=scaled, font=font, image_size=image.size)

			output_buffer = io.BytesIO()
			image.save(output_buffer, format='PNG')
			output_buffer.seek(0)
			return base64.b64encode(output_buffer.getvalue()).decode('utf-8')
		finally:
			image.close()

	def _draw_grounded_element(
		self,
		draw,
		element: GroundedElement,
		font,
		image_size: tuple[int, int],
	) -> None:
		bbox = element.bbox
		draw_enhanced_bounding_box_with_text(
			draw,
			(bbox.x, bbox.y, bbox.x + bbox.width, bbox.y + bbox.height),
			'#FF6B6B' if (element.element_type or '').lower() == 'button' else '#45B7D1',
			element.label,
			font=font,
			element_type=element.element_type or 'interactive',
			image_size=image_size,
		)