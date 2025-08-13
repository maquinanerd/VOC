# RSS to WordPress Automation System

A production-ready Python application that automatically processes entertainment news from RSS feeds, rewrites content using AI, and publishes SEO-optimized articles to WordPress.

## Features

- **Multi-source RSS Processing**: Reads from 9 entertainment news sources (ScreenRant, MovieWeb, Collider, CBR, GameRant, TheGamer)
- **AI-Powered Content Rewriting**: Uses Google Gemini API to rewrite content for SEO optimization
- **WordPress Integration**: Automatically publishes to WordPress via REST API
- **Content Deduplication**: SQLite database prevents duplicate article processing
- **Media Handling**: Supports both hotlinking and download/upload for images
- **SEO Optimization**: Optimized for Google News and Discover
- **Automated Scheduling**: Runs continuously with configurable intervals
- **Tag Extraction**: Intelligent tag extraction and internal linking
- **Error Handling**: Comprehensive error handling with exponential backoff
- **Logging**: Detailed logging with file rotation

## Architecture

The application is built with a modular architecture:

