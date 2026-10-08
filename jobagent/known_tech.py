"""Technology names people write in lowercase. A free-text answer that names one must have it in the profile.

AMBIGUOUS entries are also common English words: they count only with a tech cue (see claims._known_tech).
"""
KNOWN_TECH = set("""
kubernetes k8s docker podman helm terraform ansible puppet chef vagrant packer pulumi aws azure gcp heroku vercel
netlify cloudflare openshift nginx apache linux ubuntu debian bash powershell git github gitlab bitbucket
jenkins circleci travis argocd prometheus grafana datadog splunk kibana logstash sentry newrelic
go golang rust java kotlin scala groovy clojure haskell erlang elixir ruby rails django flask fastapi tornado
node nodejs node.js express nestjs react reactjs react.js angular angularjs vue vuejs vue.js svelte next nextjs
next.js nuxt gatsby jquery bootstrap tailwind webpack vite babel typescript javascript ecmascript html css sass
php laravel symfony wordpress drupal magento shopify dotnet .net asp.net c# c++ objective-c swift swiftui
flutter dart android ios xamarin unity unreal perl lua julia matlab fortran cobol delphi vba
mongodb postgres postgresql mysql mariadb sqlite oracle redis memcached cassandra dynamodb couchdb neo4j
elasticsearch opensearch kafka rabbitmq activemq sqs pubsub spark pyspark hadoop hive flink airflow dbt
snowflake bigquery redshift databricks tableau powerbi looker metabase superset
salesforce apex lwc hubspot dynamics sap abap odoo idempiere netsuite zoho sugarcrm pipedrive servicenow workday
zapier make n8n workato mulesoft boomi tibco jira confluence
selenium playwright cypress jest mocha pytest unittest junit testng cucumber postman soapui jmeter appium
pandas numpy scipy sklearn scikit-learn pytorch tensorflow keras xgboost lightgbm opencv huggingface
langchain llamaindex openai anthropic llm gpt chatgpt
graphql grpc rest soap oauth jwt openapi swagger kubeflow mlflow
rabbit celery sidekiq hibernate spring springboot maven gradle sbt npm yarn pnpm
django-rest firebase supabase prisma sequelize sqlalchemy
""".split())
AMBIGUOUS = {"go", "make", "spark", "rust", "swift", "dart", "ruby", "next", "node", "express", "chef", "puppet",
             "rails", "apex", "dynamics", "rest", "oracle", "unity", "unreal", "julia", "bash", "helm", "rabbit",
             "gpt", "swagger", "vagrant", "packer", "tornado", "babel", "mocha", "jest", "sentry", "boomi"}
CUES = {"lang", "language", "programming", "developer", "code", "coding", "framework", "library", "stack"}
