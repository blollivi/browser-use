from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, model_validator

from browser_use.browser import BrowserSession
from browser_use.filesystem.file_system import FileSystem
from browser_use.llm.base import BaseChatModel

if TYPE_CHECKING:
	pass


class RegisteredAction(BaseModel):
	"""Model for a registered action"""

	name: str
	description: str
	function: Callable
	param_model: type[BaseModel]

	# If True, this action is known to change the page (e.g. navigate, search, go_back, switch).
	# multi_act() will abort remaining queued actions after executing a terminates_sequence action.
	terminates_sequence: bool = False

	# filters: provide specific domains to determine whether the action should be available on the given URL or not
	domains: list[str] | None = None  # e.g. ['*.google.com', 'www.bing.com', 'yahoo.*]

	model_config = ConfigDict(arbitrary_types_allowed=True)

	def prompt_description(self) -> str:
		"""Get a description of the action for the prompt in unstructured format"""
		schema = self.param_model.model_json_schema()
		params = []

		if 'properties' in schema:
			for param_name, param_info in schema['properties'].items():
				# Build parameter description
				param_desc = param_name

				# Add type information if available
				if 'type' in param_info:
					param_type = param_info['type']
					param_desc += f'={param_type}'

				# Add description as comment if available
				if 'description' in param_info:
					param_desc += f' ({param_info["description"]})'

				params.append(param_desc)

		# Format: action_name: Description. (param1=type, param2=type, ...)
		if params:
			return f'{self.name}: {self.description}. ({", ".join(params)})'
		else:
			return f'{self.name}: {self.description}'


class ActionModel(BaseModel):
	"""Base model for dynamically created action models"""

	# this will have all the registered actions, e.g.
	# click_element = param_model = ClickElementParams
	# done = param_model = None
	#
	model_config = ConfigDict(arbitrary_types_allowed=True, extra='forbid')

	@model_validator(mode='before')
	@classmethod
	def _fix_flattened_action_params(cls, v: object) -> object:
		"""Recover when LLMs (e.g. Gemini Flash) flatten nested action params.

		Handles two patterns:
		1. Key=value style leaked params:
		   {"click": "coordinate_x=330", "coordinate_y=309": null}
		   → {"click": {"coordinate_x": 330, "coordinate_y": 309}}

		2. Extra keys at the outer level that belong inside the action params:
		   {"done": "Task complete", "success": true}
		   → {"done": {"text": "Task complete", "success": true}}
		"""
		if not isinstance(v, dict):
			return v

		# Get valid field names for this specific (dynamically created) model
		valid_fields: set[str] = set(cls.model_fields.keys()) if hasattr(cls, 'model_fields') else set()

		# --- Pass 1: handle "key=value" style leaked params ---
		leaked: dict[str, Any] = {}
		normal: dict[str, Any] = {}
		for key, val in v.items():
			if '=' in str(key):
				param_name, _, raw = str(key).partition('=')
				try:
					leaked[param_name] = int(raw) if raw.lstrip('-').isdigit() else raw
				except (ValueError, TypeError):
					leaked[param_name] = raw
			else:
				normal[key] = val

		if leaked:
			result: dict[str, Any] = {}
			for action_key, action_value in normal.items():
				if isinstance(action_value, str) and '=' in action_value:
					param_name, _, raw = action_value.partition('=')
					try:
						action_dict: dict[str, Any] = {param_name: int(raw) if raw.lstrip('-').isdigit() else raw}
					except (ValueError, TypeError):
						action_dict = {param_name: raw}
					action_dict.update(leaked)
					result[action_key] = action_dict
				elif isinstance(action_value, dict):
					merged = dict(action_value)
					merged.update(leaked)
					result[action_key] = merged
				else:
					result[action_key] = action_value
			return result

		# --- Pass 2: handle extra non-action keys leaked into the outer dict ---
		# e.g. {"done": "text", "success": True} → {"done": {"text": "text", "success": True}}
		if valid_fields:
			action_keys = [k for k in v if k in valid_fields]
			extra_keys = [k for k in v if k not in valid_fields]
			if len(action_keys) == 1 and extra_keys:
				action_key = action_keys[0]
				action_value = v[action_key]
				extra = {k: v[k] for k in extra_keys}
				if isinstance(action_value, dict):
					merged_val = dict(action_value)
					merged_val.update(extra)
					return {action_key: merged_val}
				elif isinstance(action_value, str):
					# Convert the string via the param model's own coercer to get a base dict,
					# then merge the extra keys (e.g. "success: True" from DoneAction).
					field_info = cls.model_fields.get(action_key)
					param_type = field_info.annotation if field_info else None
					if param_type is not None and isinstance(param_type, type) and issubclass(param_type, BaseModel):
						try:
							converted = param_type.model_validate(action_value)
							base_dict = converted.model_dump()
							base_dict.update(extra)
							return {action_key: base_dict}
						except Exception:
							pass
						# Second try: map the string to the first str-typed field in the param model
						# and merge extra keys. Handles flat formats like:
						# {"input": "Jean", "coordinate_x": 764, "coordinate_y": 376}
						# → {"input": {"text": "Jean", "coordinate_x": 764, "coordinate_y": 376}}
						str_field = next(
							(fname for fname, finfo in param_type.model_fields.items() if finfo.annotation is str),
							None,
						)
						if str_field:
							merged: dict[str, Any] = {str_field: action_value}
							merged.update(extra)
							return {action_key: merged}
					# Fallback: keep string as-is, drop unrecognised extras
					return {action_key: action_value}

		return v

	def get_index(self) -> int | None:
		"""Get the index of the action"""
		# {'clicked_element': {'index':5}}
		params = self.model_dump(exclude_unset=True).values()
		if not params:
			return None
		for param in params:
			if param is not None and 'index' in param:
				return param['index']
		return None

	def set_index(self, index: int):
		"""Overwrite the index of the action"""
		# Get the action name and params
		action_data = self.model_dump(exclude_unset=True)
		action_name = next(iter(action_data.keys()))
		action_params = getattr(self, action_name)

		# Update the index directly on the model
		if hasattr(action_params, 'index'):
			action_params.index = index


class ActionRegistry(BaseModel):
	"""Model representing the action registry"""

	actions: dict[str, RegisteredAction] = {}

	@staticmethod
	def _match_domains(domains: list[str] | None, url: str) -> bool:
		"""
		Match a list of domain glob patterns against a URL.

		Args:
			domains: A list of domain patterns that can include glob patterns (* wildcard)
			url: The URL to match against

		Returns:
			True if the URL's domain matches the pattern, False otherwise
		"""

		if domains is None or not url:
			return True

		# Use the centralized URL matching logic from utils
		from browser_use.utils import match_url_with_domain_pattern

		for domain_pattern in domains:
			if match_url_with_domain_pattern(url, domain_pattern):
				return True
		return False

	def get_prompt_description(self, page_url: str | None = None) -> str:
		"""Get a description of all actions for the prompt

		Args:
			page_url: If provided, filter actions by URL using domain filters.

		Returns:
			A string description of available actions.
			- If page is None: return only actions with no page_filter and no domains (for system prompt)
			- If page is provided: return only filtered actions that match the current page (excluding unfiltered actions)
		"""
		if page_url is None:
			# For system prompt (no URL provided), include only actions with no filters
			return '\n'.join(action.prompt_description() for action in self.actions.values() if action.domains is None)

		# only include filtered actions for the current page URL
		filtered_actions = []
		for action in self.actions.values():
			if not action.domains:
				# skip actions with no filters, they are already included in the system prompt
				continue

			# Check domain filter
			if self._match_domains(action.domains, page_url):
				filtered_actions.append(action)

		return '\n'.join(action.prompt_description() for action in filtered_actions)


class SpecialActionParameters(BaseModel):
	"""Model defining all special parameters that can be injected into actions"""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	# optional user-provided context object passed down from Agent(context=...)
	# e.g. can contain anything, external db connections, file handles, queues, runtime config objects, etc.
	# that you might want to be able to access quickly from within many of your actions
	# browser-use code doesn't use this at all, we just pass it down to your actions for convenience
	context: Any | None = None

	# browser-use session object, can be used to create new tabs, navigate, access CDP
	browser_session: BrowserSession | None = None

	# Current page URL for filtering and context
	page_url: str | None = None

	# CDP client for direct Chrome DevTools Protocol access
	cdp_client: Any | None = None  # CDPClient type from cdp_use

	# extra injected config if the action asks for these arg names
	page_extraction_llm: BaseChatModel | None = None
	file_system: FileSystem | None = None
	available_file_paths: list[str] | None = None
	has_sensitive_data: bool = False
	extraction_schema: dict | None = None

	@classmethod
	def get_browser_requiring_params(cls) -> set[str]:
		"""Get parameter names that require browser_session"""
		return {'browser_session', 'cdp_client', 'page_url'}
