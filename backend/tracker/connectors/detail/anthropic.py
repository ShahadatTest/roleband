"""Anthropic company detail add-on over the Greenhouse source contract."""

from tracker.connectors.detail.greenhouse import GreenhouseDetailConnector


class AnthropicDetailConnector(GreenhouseDetailConnector):
    source = "anthropic"
