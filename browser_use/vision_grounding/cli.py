from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv

from browser_use import Agent, BrowserProfile, BrowserSession, ChatAnthropic, ChatBrowserUse, ChatGoogle, ChatOpenAI


VisionGroundingModeArg = Literal['vision', 'fallback', 'off']


@dataclass(frozen=True)
class VisionGroundingCLIConfig:
	provider: Literal['browser-use', 'openai', 'google', 'anthropic']
	model: str | None
	task: str
	mode: VisionGroundingModeArg
	headless: bool
	max_steps: int
	max_actions_per_step: int
	user_data_dir: str | None
	keep_alive: bool
	allowed_domains: list[str] | None


def _default_model_for_provider(provider: str) -> str:
	defaults = {
		'browser-use': 'bu-latest',
		'openai': 'gpt-5',
		'google': 'gemini-3-pro-preview',
		'anthropic': 'claude-sonnet-4-5',
	}
	return defaults[provider]


def _mode_to_agent_value(mode: VisionGroundingModeArg) -> bool | Literal['fallback']:
	if mode == 'vision':
		return True
	if mode == 'fallback':
		return 'fallback'
	return False


def _required_api_key_env(provider: str) -> str:
	required = {
		'browser-use': 'BROWSER_USE_API_KEY',
		'openai': 'OPENAI_API_KEY',
		'google': 'GOOGLE_API_KEY',
		'anthropic': 'ANTHROPIC_API_KEY',
	}
	return required[provider]


def validate_provider_env(provider: str) -> None:
	env_var = _required_api_key_env(provider)
	if os.getenv(env_var):
		return
	raise ValueError(
		f'{env_var} is not set. Add it to your environment or .env file before running the CLI. '
		f'Example: export {env_var}=your_api_key'
	)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description='Run a browser-use agent with vision grounding enabled for manual testing.'
	)
	parser.add_argument(
		'task',
		nargs='?',
		default='Open https://example.com and describe the visible interactive elements.',
		help='Task for the agent to run.',
	)
	parser.add_argument(
		'--provider',
		choices=['browser-use', 'openai', 'google', 'anthropic'],
		default='google',
		help='LLM provider to use for both the agent and the grounding model.',
	)
	parser.add_argument('--model', help='Override the default model for the selected provider.')
	parser.add_argument(
		'--mode',
		choices=['vision', 'fallback', 'off'],
		default='vision',
		help='Vision grounding mode: always on, fallback only, or disabled.',
	)
	parser.add_argument('--headless', action='store_true', help='Run the browser headlessly.')
	parser.add_argument('--max-steps', type=int, default=12, help='Maximum number of agent steps.')
	parser.add_argument(
		'--max-actions-per-step',
		type=int,
		default=3,
		help='Maximum number of actions the agent can emit per step.',
	)
	parser.add_argument('--user-data-dir', help='Optional browser profile directory.')
	parser.add_argument(
		'--keep-alive',
		action='store_true',
		help='Keep the browser session alive after the agent run finishes.',
	)
	parser.add_argument(
		'--allowed-domain',
		dest='allowed_domains',
		action='append',
		help='Restrict browsing to a domain pattern. Repeat to allow multiple domains.',
	)
	return parser


def parse_args(argv: list[str] | None = None) -> VisionGroundingCLIConfig:
	args = build_parser().parse_args(argv)
	return VisionGroundingCLIConfig(
		provider=args.provider,
		model=args.model,
		task=args.task,
		mode=args.mode,
		headless=args.headless,
		max_steps=args.max_steps,
		max_actions_per_step=args.max_actions_per_step,
		user_data_dir=args.user_data_dir,
		keep_alive=args.keep_alive,
		allowed_domains=args.allowed_domains,
	)


def build_llm(provider: str, model: str | None):
	validate_provider_env(provider)
	resolved_model = model or _default_model_for_provider(provider)
	if provider == 'browser-use':
		return ChatBrowserUse(model=resolved_model)
	if provider == 'openai':
		return ChatOpenAI(model=resolved_model, temperature=0.0)
	if provider == 'google':
		return ChatGoogle(model=resolved_model, temperature=0.0)
	if provider == 'anthropic':
		return ChatAnthropic(model=resolved_model)
	raise ValueError(f'Unsupported provider: {provider}')


async def run_cli(config: VisionGroundingCLIConfig) -> None:
	load_dotenv()

	llm = build_llm(config.provider, config.model)
	browser_profile = BrowserProfile(
		headless=config.headless,
		keep_alive=config.keep_alive,
		user_data_dir=config.user_data_dir,
		allowed_domains=config.allowed_domains,
	)
	browser_session = BrowserSession(browser_profile=browser_profile)
	agent = Agent(
		task=config.task,
		llm=llm,
		browser_session=browser_session,
		use_vision=True,
		use_vision_grounding=_mode_to_agent_value(config.mode),
		vision_grounding_llm=llm,
		max_actions_per_step=config.max_actions_per_step,
	)

	print('browser-use vision grounding test CLI')
	print(f'provider={config.provider} model={getattr(llm, "model", config.model)} mode={config.mode}')
	print(f'headless={config.headless} max_steps={config.max_steps} task={config.task}')

	try:
		history = await agent.run(max_steps=config.max_steps)
		print('\nRun complete.')
		print(f'success={history.is_successful()} done={history.is_done()} steps={history.number_of_steps()}')
		final_result = history.final_result()
		if final_result:
			print('\nFinal result:')
			print(final_result)
	finally:
		if not config.keep_alive:
			await browser_session.kill()


def main(argv: list[str] | None = None) -> None:
	config = parse_args(argv)
	asyncio.run(run_cli(config))


if __name__ == '__main__':
	main()