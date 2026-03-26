from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema


# Action Input Models
class ExtractAction(BaseModel):
	query: str
	extract_links: bool = Field(
		default=False, description='Set True to true if the query requires links, else false to safe tokens'
	)
	extract_images: bool = Field(
		default=False,
		description='Set True to include image src URLs in extracted markdown. Auto-enabled when query contains image-related keywords.',
	)
	start_from_char: int = Field(
		default=0, description='Use this for long markdowns to start from a specific character (not index in browser_state)'
	)
	output_schema: SkipJsonSchema[dict | None] = Field(
		default=None,
		description='Optional JSON Schema dict. When provided, extraction returns validated JSON matching this schema instead of free-text.',
	)
	already_collected: list[str] = Field(
		default_factory=list,
		description='Item identifiers (name, URL, or ID) already collected in prior extract calls on other pages. The extractor will skip items matching these to prevent duplicates. Use when paginating across multiple pages.',
	)


class SearchPageAction(BaseModel):
	pattern: str = Field(description='Text or regex pattern to search for in page content')
	regex: bool = Field(default=False, description='Treat pattern as regex (default: literal text match)')
	case_sensitive: bool = Field(default=False, description='Case-sensitive search (default: case-insensitive)')
	context_chars: int = Field(default=150, description='Characters of surrounding context per match')
	css_scope: str | None = Field(default=None, description='CSS selector to limit search scope (e.g. "div#main")')
	max_results: int = Field(default=25, description='Maximum matches to return')


class FindElementsAction(BaseModel):
	selector: str = Field(description='CSS selector to query elements (e.g. "table tr", "a.link", "div.product")')
	attributes: list[str] | None = Field(
		default=None,
		description='Specific attributes to extract (e.g. ["href", "src", "class"]). If not set, returns tag and text only.',
	)
	max_results: int = Field(default=50, description='Maximum elements to return')
	include_text: bool = Field(default=True, description='Include text content of each element')


class SearchAction(BaseModel):
	query: str
	engine: str = Field(
		default='duckduckgo', description='duckduckgo, google, bing (use duckduckgo by default because less captchas)'
	)


# Backward compatibility alias
SearchAction = SearchAction


class NavigateAction(BaseModel):
	url: str
	new_tab: bool = Field(default=False)

	@model_validator(mode='before')
	@classmethod
	def coerce_string(cls, v: object) -> object:
		"""Allow LLMs to pass a plain URL string instead of {"url": "..."}."""
		if isinstance(v, str):
			return {'url': v}
		return v


# Backward compatibility alias
GoToUrlAction = NavigateAction


class ClickElementAction(BaseModel):
	index: int | None = Field(default=None, ge=1, description='Element index from browser_state')
	coordinate_x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')
	# expect_download: bool = Field(default=False, description='set True if expecting a download, False otherwise')  # moved to downloads_watchdog.py
	# click_count: int = 1  # TODO

	@model_validator(mode='before')
	@classmethod
	def coerce_int_to_index(cls, value: object) -> object:
		"""Accept a plain integer as {index: int} or [x, y] list as coordinates for backward-compat with LLMs."""
		if isinstance(value, int):
			return {'index': value}
		if isinstance(value, (list, tuple)) and len(value) == 2:
			return {'coordinate_x': value[0], 'coordinate_y': value[1]}
		return value


class ClickElementActionIndexOnly(BaseModel):
	model_config = ConfigDict(title='ClickElementAction')

	index: int = Field(ge=1, description='Element index from browser_state')

	@model_validator(mode='before')
	@classmethod
	def coerce_int_to_index(cls, value: object) -> object:
		"""Accept a plain integer as {index: int} for backward-compat with LLMs using the old schema."""
		if isinstance(value, int):
			return {'index': value}
		return value


class ClickElementActionCoordinateOnly(BaseModel):
	model_config = ConfigDict(title='ClickElementAction')

	coordinate_x: int = Field(description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int = Field(description='Vertical coordinate relative to viewport top edge')

	@model_validator(mode='before')
	@classmethod
	def coerce_list(cls, value: object) -> object:
		"""Accept [x, y] list or 'x, y' string as {'coordinate_x': x, 'coordinate_y': y}."""
		if isinstance(value, (list, tuple)) and len(value) == 2:
			return {'coordinate_x': value[0], 'coordinate_y': value[1]}
		if isinstance(value, str):
			# Handle "x, y", "x,y", or "(x, y)" string formats produced by weaker LLMs
			cleaned = value.strip().strip('()')
			parts = [p.strip() for p in cleaned.split(',')]
			if len(parts) == 2:
				try:
					return {'coordinate_x': int(float(parts[0])), 'coordinate_y': int(float(parts[1]))}
				except (ValueError, TypeError):
					pass
		return value


class InputTextAction(BaseModel):
	index: int | None = Field(default=None, ge=0, description='Element index from browser_state')
	coordinate_x: int | None = Field(default=None, description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int | None = Field(default=None, description='Vertical coordinate relative to viewport top edge')
	text: str
	clear: bool = Field(default=True, description='1=clear, 0=append')

	@model_validator(mode='after')
	def validate_target(self) -> 'InputTextAction':
		if self.index is None and (self.coordinate_x is None or self.coordinate_y is None):
			raise ValueError('Provide either index or both coordinate_x and coordinate_y')
		return self


class InputTextActionCoordinateOnly(BaseModel):
	model_config = ConfigDict(title='InputTextAction')

	coordinate_x: int = Field(description='Horizontal coordinate relative to viewport left edge')
	coordinate_y: int = Field(description='Vertical coordinate relative to viewport top edge')
	text: str
	clear: bool = Field(default=True, description='1=clear, 0=append')

	@model_validator(mode='before')
	@classmethod
	def coerce_list(cls, value: object) -> object:
		"""Accept [x, y, text] or [x, y, text, clear] lists from weaker LLMs."""
		if isinstance(value, (list, tuple)) and len(value) >= 3:
			result: dict[str, object] = {'coordinate_x': value[0], 'coordinate_y': value[1], 'text': value[2]}
			if len(value) >= 4:
				result['clear'] = value[3]
			return result
		return value


class DoneAction(BaseModel):
	@model_validator(mode='before')
	@classmethod
	def coerce_string(cls, value: object) -> object:
		"""Accept a plain string as {'text': string}."""
		if isinstance(value, str):
			return {'text': value}
		return value

	text: str = Field(
		description=(
			'Final message to the user. '
			'ONLY report data you directly observed in browser_state, tool outputs, or screenshots during this session. '
			'Do NOT use training knowledge to fill gaps — if information was not found on the page, say so explicitly. '
			'Do NOT claim completion of steps from compacted_memory or prior session summaries '
			'unless you explicitly verified them yourself. '
			'If uncertain whether a prior step completed, say so explicitly.'
		)
	)
	success: bool = Field(default=True, description='True if user_request completed successfully')
	files_to_display: list[str] | None = Field(default=[])


T = TypeVar('T', bound=BaseModel)


def _hide_internal_fields_from_schema(schema: dict) -> None:
	"""Remove internal fields from the JSON schema to avoid collisions with user models."""
	props = schema.get('properties', {})
	props.pop('success', None)
	props.pop('files_to_display', None)


class StructuredOutputAction(BaseModel, Generic[T]):
	model_config = ConfigDict(json_schema_extra=_hide_internal_fields_from_schema)

	success: bool = Field(default=True, description='True if user_request completed successfully')
	data: T = Field(description='The actual output data matching the requested schema')
	files_to_display: list[str] | None = Field(default=[])


class SwitchTabAction(BaseModel):
	tab_id: str = Field(min_length=4, max_length=4, description='4-char id')

	@model_validator(mode='before')
	@classmethod
	def coerce_string(cls, v: object) -> object:
		if isinstance(v, str):
			return {'tab_id': v}
		return v


class CloseTabAction(BaseModel):
	tab_id: str = Field(min_length=4, max_length=4, description='4-char id')

	@model_validator(mode='before')
	@classmethod
	def coerce_string(cls, v: object) -> object:
		if isinstance(v, str):
			return {'tab_id': v}
		return v


class ScrollAction(BaseModel):
	down: bool = Field(default=True, description='down=True=scroll down, down=False scroll up')
	pages: float = Field(default=1.0, description='0.5=half page, 1=full page, 10=to bottom/top')
	index: int | None = Field(default=None, description='Optional element index to scroll within specific element')


class ScrollActionCoordinateOnly(BaseModel):
	model_config = ConfigDict(title='ScrollAction')

	down: bool = Field(default=True, description='down=True=scroll down, down=False scroll up')
	pages: float = Field(default=1.0, description='0.5=half page, 1=full page, 10=to bottom/top')

	@model_validator(mode='before')
	@classmethod
	def coerce_list(cls, value: object) -> object:
		"""Accept coordinate-scroll lists from weaker LLMs.

		[x, y]: positive y → scroll down, negative y → scroll up.
		[x, y, direction]: direction string ('down'/'up') overrides sign of y.
		pages is estimated from |y| (400 px ≈ 1 page).
		"""
		if isinstance(value, (list, tuple)) and len(value) >= 2:
			y = value[1]
			try:
				y_num = float(y)
			except (TypeError, ValueError):
				return value
			scroll_down = y_num >= 0
			# 3rd element may be a direction string e.g. 'down', 'up'
			if len(value) >= 3:
				direction = str(value[2]).strip().lower()
				if direction == 'up':
					scroll_down = False
				elif direction == 'down':
					scroll_down = True
			return {'down': scroll_down, 'pages': max(0.5, abs(y_num) / 400)}
		return value


class SendKeysAction(BaseModel):
	keys: str = Field(description='keys (Escape, Enter, PageDown) or shortcuts (Control+o)')


class UploadFileAction(BaseModel):
	index: int
	path: str


class NoParamsAction(BaseModel):
	model_config = ConfigDict(extra='ignore')

	# Optional field required by Gemini API which errors on empty objects in response_schema
	description: str | None = Field(None, description='Optional description for the action')


class ScreenshotAction(BaseModel):
	model_config = ConfigDict(extra='ignore')

	file_name: str | None = Field(
		default=None,
		description='If provided, saves screenshot to this file and returns path. Otherwise screenshot is included in next observation.',
	)


class SaveAsPdfAction(BaseModel):
	file_name: str | None = Field(
		default=None,
		description='Output PDF filename (without path). Defaults to page title. Extension .pdf is added automatically if missing.',
	)
	print_background: bool = Field(default=True, description='Include background graphics and colors')
	landscape: bool = Field(default=False, description='Use landscape orientation')
	scale: float = Field(default=1.0, ge=0.1, le=2.0, description='Scale of the webpage rendering (0.1 to 2.0)')
	paper_format: str = Field(
		default='Letter',
		description='Paper size: Letter, Legal, A4, A3, or Tabloid',
	)


class GetDropdownOptionsAction(BaseModel):
	index: int


class SelectDropdownOptionAction(BaseModel):
	index: int
	text: str = Field(description='exact text/value')
