import pytest

from browser_use.vision_grounding.cli import _mode_to_agent_value, parse_args, validate_provider_env


def test_parse_args_uses_vision_defaults():
	config = parse_args([])

	assert config.provider == 'google'
	assert config.mode == 'vision'
	assert config.max_steps == 12
	assert config.max_actions_per_step == 3
	assert config.headless is False


def test_parse_args_accepts_explicit_flags():
	config = parse_args(
		[
			'Open https://example.com and click the search box',
			'--provider',
			'openai',
			'--model',
			'gpt-5-mini',
			'--mode',
			'fallback',
			'--headless',
			'--max-steps',
			'5',
			'--max-actions-per-step',
			'2',
			'--allowed-domain',
			'example.com',
		]
	)

	assert config.task == 'Open https://example.com and click the search box'
	assert config.provider == 'openai'
	assert config.model == 'gpt-5-mini'
	assert config.mode == 'fallback'
	assert config.headless is True
	assert config.max_steps == 5
	assert config.max_actions_per_step == 2
	assert config.allowed_domains == ['example.com']


def test_mode_mapping_matches_agent_settings_values():
	assert _mode_to_agent_value('vision') is True
	assert _mode_to_agent_value('fallback') == 'fallback'
	assert _mode_to_agent_value('off') is False


def test_validate_provider_env_requires_expected_env_var(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.delenv('GOOGLE_API_KEY', raising=False)

	with pytest.raises(ValueError, match='GOOGLE_API_KEY is not set'):
		validate_provider_env('google')


def test_validate_provider_env_accepts_present_env_var(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv('GOOGLE_API_KEY', 'test-key')

	validate_provider_env('google')