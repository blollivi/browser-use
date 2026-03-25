from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
	model_config = ConfigDict(extra='forbid')

	x: int = Field(ge=0)
	y: int = Field(ge=0)
	width: int = Field(gt=0)
	height: int = Field(gt=0)

	@property
	def center_x(self) -> int:
		return self.x + self.width // 2

	@property
	def center_y(self) -> int:
		return self.y + self.height // 2


class GroundedElement(BaseModel):
	model_config = ConfigDict(extra='forbid')

	label: str = Field(min_length=1, description='Short unique label visible in the annotated screenshot, e.g. A1 or SEARCH_BUTTON.')
	bbox: BoundingBox
	element_type: str | None = Field(
		default=None,
		description='Approximate UI element type, e.g. button, input, link, dropdown, checkbox.',
	)


class VisionGroundingResult(BaseModel):
	model_config = ConfigDict(extra='forbid')

	elements: list[GroundedElement] = Field(default_factory=list)

	def to_prompt_lines(self) -> list[str]:
		lines: list[str] = []
		for element in self.elements:
			element_type = element.element_type or 'interactive'
			bbox = element.bbox
			lines.append(
				f'[{element.label}] <{element_type}> '
				f'center=({bbox.center_x}, {bbox.center_y})'
			)
		return lines