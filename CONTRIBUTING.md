# Contributing to RFLink Modern

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/ha-rflink-modern.git`
3. Create a feature branch: `git checkout -b feature/my-feature`
4. Make your changes
5. Test with your Home Assistant instance
6. Commit and push: `git push origin feature/my-feature`
7. Open a Pull Request

## Development Setup

```bash
# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dev dependencies
pip install homeassistant rflink pytest pytest-homeassistant-custom-component
```

## Code Style

* Follow Home Assistant's [development guidelines](https://developers.home-assistant.io/docs/development_guidelines)
* Use type hints everywhere
* Document public methods with docstrings
* Keep imports sorted (stdlib → third-party → local)

## Testing

```bash
pytest tests/
```

## Translations

Translation files live in `custom_components/rflink_modern/translations/`.
To add a new language, copy `en.json` to `<language_code>.json` and translate
all values (keep the keys as-is).

Currently supported: English (`en`), German (`de`).

## Reporting Issues

Please include:

* Your Home Assistant version
* Your RFLink firmware version
* The relevant log output (`grep rflink_modern home-assistant.log`)
* Steps to reproduce the issue


| test | bla |
| ---- | --- |
| schaumal |  |


