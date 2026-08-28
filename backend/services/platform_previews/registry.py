"""Configured live preview providers."""

from backend.services.platform_previews.engine import MarkdownPreviewProvider, PreviewEngine
from backend.services.platform_previews.hashnode import HashnodePreviewProvider


preview_engine = PreviewEngine([MarkdownPreviewProvider(), HashnodePreviewProvider()])
