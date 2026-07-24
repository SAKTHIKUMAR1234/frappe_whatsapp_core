### Frappe WhatsApp Core

Reusable, configurable WhatsApp business workflow foundation

### Core Flow Builder

Open **WhatsApp Core Flow**, create a draft, then click **Open Flow Builder**.
The Desk page supports drag-and-drop nodes, visual connections, triggers,
validation and immutable publication.

Available node families:

- template/message/question
- condition and guarded loop
- typed action or external connector
- wait and human handoff
- end

Solution apps add business actions without changing the relay or the Core
engine.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app frappe_whatsapp_core
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_whatsapp_core
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
