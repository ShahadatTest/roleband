### keyed: product vocabulary looked up by the slug the API sends. The backend
### owns the slugs and their meaning; this file names them. `backend/tests/test_vocab_catalog.py`
### fails when a slug the backend can send has no message here. `src/copy/vocab.ts` reads it.

## Domains: backend/tracker/taxonomy/domains.py DOMAIN_GROUPS; the hint is the line under the name
# kind=name wording=as-is
vocab-domain-logistics-fulfillment = Logistics & Fulfillment
# kind=tooltip wording=as-is
vocab-domain-hint-logistics-fulfillment = Supply chain, warehouses
# kind=name wording=as-is
vocab-domain-facilities-realestate = Facilities & Real Estate
# kind=tooltip wording=as-is
vocab-domain-hint-facilities-realestate = Buildings, construction
# kind=name wording=as-is
vocab-domain-retail-commerce = Retail & Commerce
# kind=tooltip wording=as-is
vocab-domain-hint-retail-commerce = Marketplaces, grocery
# kind=name wording=as-is
vocab-domain-advertising = Advertising
# kind=tooltip wording=as-is
vocab-domain-hint-advertising = Ad tech, programmatic
# kind=name wording=as-is
vocab-domain-marketing-brand = Marketing & Brand
# kind=tooltip wording=as-is
vocab-domain-hint-marketing-brand = Demand gen, PR, comms
# kind=name wording=as-is
vocab-domain-media-entertainment = Media & Entertainment
# kind=tooltip wording=as-is
vocab-domain-hint-media-entertainment = Streaming, games, music
# kind=name wording=as-is
vocab-domain-public-sector = Public Sector & Defense
# kind=tooltip wording=as-is
vocab-domain-hint-public-sector = Federal, state, aerospace
# kind=name wording=as-is
vocab-domain-health-bio = Health & Life Sciences
# kind=tooltip wording=as-is
vocab-domain-hint-health-bio = Clinical, medical, biotech
# kind=name wording=as-is
vocab-domain-security-privacy = Security, Privacy & Trust
# kind=tooltip wording=as-is
vocab-domain-hint-security-privacy = Fraud, abuse, safety
# kind=name wording=as-is
vocab-domain-ai-ml = AI & Machine Learning
# kind=tooltip wording=as-is
vocab-domain-hint-ai-ml = LLMs, applied science
# kind=name wording=as-is
vocab-domain-cloud-infra = Cloud & Infrastructure
# kind=tooltip wording=as-is
vocab-domain-hint-cloud-infra = Compute, data centers
# kind=name wording=as-is
vocab-domain-devices-hardware = Devices & Hardware
# kind=tooltip wording=as-is
vocab-domain-hint-devices-hardware = Chips, wearables, robotics
# kind=name wording=as-is
vocab-domain-data-analytics = Data & Analytics
# kind=tooltip wording=as-is
vocab-domain-hint-data-analytics = BI, dashboards, pipelines
# kind=name wording=as-is
vocab-domain-developer-platform = Developer & Productivity Platform
# kind=tooltip wording=as-is
vocab-domain-hint-developer-platform = Tooling, APIs, SDKs
# kind=name wording=as-is
vocab-domain-payments-fintech = Payments & Fintech
# kind=tooltip wording=as-is
vocab-domain-hint-payments-fintech = Billing, wallets, treasury
# kind=name wording=as-is
vocab-domain-finance-accounting = Finance & Accounting
# kind=tooltip wording=as-is
vocab-domain-hint-finance-accounting = FP&A, tax, audit
# kind=name wording=as-is
vocab-domain-people-workplace = People & Workplace
# kind=tooltip wording=as-is
vocab-domain-hint-people-workplace = HR, recruiting, talent
# kind=name wording=as-is
vocab-domain-customer-support = Customer Support & Service
# kind=tooltip wording=as-is
vocab-domain-hint-customer-support = Help desk, user ops
# kind=name wording=as-is
vocab-domain-corporate-operations = Corporate Operations
# kind=tooltip wording=as-is
vocab-domain-hint-corporate-operations = Strategy, planning, BizOps
# kind=name wording=as-is
vocab-domain-unclassified = Unclassified

## Tracks: backend/tracker/taxonomy/tracks.py TRACKS
# kind=name wording=as-is
vocab-track-management = Management / Leadership
# kind=name wording=as-is
vocab-track-product-program = Product & Program
# kind=name wording=as-is
vocab-track-technical = Technical (IC)
# kind=name wording=as-is
vocab-track-business-customer = Business & Customer (IC)

## Role groups: backend/tracker/taxonomy/roles.py ROLE_GROUPS; `other` names a role in none
# kind=name wording=as-is
vocab-role-engineering-management = Engineering Management
# kind=name wording=as-is
vocab-role-product-management = Product Management
# kind=name wording=as-is
vocab-role-technical-program-management = Technical Program Management (TPM)
# kind=name wording=as-is
vocab-role-program-management = Program / Project Management
# kind=name wording=as-is
vocab-role-ml-ai-research = ML / AI Research
# kind=name wording=as-is
vocab-role-data-science = Data Science & Analytics
# kind=name wording=as-is
vocab-role-data-engineering = Data Engineering
# kind=name wording=as-is
vocab-role-security-engineering = Security
# kind=name wording=as-is
vocab-role-infrastructure-sre = Infrastructure / SRE / Systems
# kind=name wording=as-is
vocab-role-hardware-engineering = Hardware / Silicon
# kind=name wording=as-is
vocab-role-software-engineering = Software Engineering
# kind=name wording=as-is
vocab-role-design-ux = Design / UX
# kind=name wording=as-is
vocab-role-developer-relations = Developer Relations
# kind=name wording=as-is
vocab-role-solutions-sales-eng = Solutions / Forward-Deployed
# kind=name wording=as-is
vocab-role-technical-writing = Technical Writing
# kind=name wording=as-is
vocab-role-it-support = IT / Support Engineering
# kind=name wording=as-is
vocab-role-sales-business-development = Sales & Business Development
# kind=name wording=as-is
vocab-role-customer-success = Customer Success & Service
# kind=name wording=as-is
vocab-role-marketing-communications = Marketing & Communications
# kind=name wording=as-is
vocab-role-business-operations-strategy = Business Operations & Strategy
# kind=name wording=as-is
vocab-role-operations-facilities = Operations & Facilities
# kind=name wording=as-is same-as=vocab-domain-finance-accounting
vocab-role-finance-accounting = Finance & Accounting
# kind=name wording=as-is
vocab-role-people-recruiting = People / HR / Recruiting
# kind=name wording=as-is
vocab-role-legal-policy = Legal / Policy / Compliance
# kind=name wording=as-is
vocab-role-other = Other

## Company sectors: backend/tracker/company_discovery.py SECTORS
# kind=name wording=as-is
vocab-sector-faang = FAANG
# kind=name wording=as-is
vocab-sector-ai = AI
# kind=name wording=as-is
vocab-sector-technology = Technology
# kind=name wording=as-is
vocab-sector-gaming = Gaming
# kind=name wording=as-is
vocab-sector-consulting = Consulting
# kind=name wording=as-is
vocab-sector-fintech = Fintech & payments
# kind=name wording=as-is
vocab-sector-quant = Quantitative trading
# kind=name wording=as-is
vocab-sector-cybersecurity = Cybersecurity
# kind=name wording=as-is
vocab-sector-cloud-data-devtools = Cloud, data & devtools
# kind=name wording=as-is
vocab-sector-semiconductors = Semiconductors & compute
# kind=name wording=as-is
vocab-sector-robotics = Robotics, autonomy & defense
# kind=name wording=as-is
vocab-sector-consumer = Consumer platforms

## Where a company fact came from: backend/tracker/profiles/sources.py SOURCES
# kind=name wording=as-is
vocab-source-manual = Manual (you)
# kind=name wording=as-is
vocab-source-sec-edgar = SEC EDGAR
# kind=name wording=as-is
vocab-source-dol-lca = DOL LCA
# kind=name wording=as-is
vocab-source-market = Market data
# kind=name
vocab-source-roleband = Built-in data
# kind=name wording=as-is
vocab-source-blueprint = Blueprint seed
# kind=name wording=as-is
vocab-source-heuristic = Inferred
# kind=name
vocab-source-employer = Employer-stated
# kind=name
vocab-source-reported = Estimated
# kind=label
vocab-source-estimated = Estimated

## Skills: backend/tracker/skills/catalog.yaml, named as the catalog names them (not Python, so not as-is)
# kind=name same-as=vocab-domain-advertising
vocab-skill-ads = Advertising
# kind=name
vocab-skill-ai-agents = AI Agents
# kind=name
vocab-skill-airflow = Airflow
# kind=name
vocab-skill-api-design = API Design
# kind=name
vocab-skill-appsec = Application Security
# kind=name
vocab-skill-aspnet = ASP.NET
# kind=name
vocab-skill-authentication = AuthN / AuthZ
# kind=name
vocab-skill-aws = AWS
# kind=name
vocab-skill-aws-s3 = AWS S3
# kind=name
vocab-skill-azure = Azure
# kind=name
vocab-skill-bash-shell = Shell / Bash
# kind=name
vocab-skill-bigquery = BigQuery
# kind=name
vocab-skill-c-lang = C
# kind=name
vocab-skill-causal-inference = Causal Inference
# kind=name
vocab-skill-cicd = CI/CD
# kind=name
vocab-skill-communication = Communication
# kind=name
vocab-skill-computer-vision = Computer Vision
# kind=name
vocab-skill-cpp = C++
# kind=name
vocab-skill-cross-functional = Cross-functional Collaboration
# kind=name
vocab-skill-cryptography = Cryptography
# kind=name
vocab-skill-csharp = C#
# kind=name
vocab-skill-cuda = CUDA / GPU
# kind=name
vocab-skill-data-pipeline = Data Pipelines
# kind=name
vocab-skill-data-warehouse = Data Warehousing
# kind=name
vocab-skill-deep-learning = Deep Learning
# kind=name
vocab-skill-diffusion = Diffusion Models
# kind=name
vocab-skill-distributed-systems = Distributed Systems
# kind=name
vocab-skill-distributed-training = Distributed Training
# kind=name
vocab-skill-docker = Docker
# kind=name
vocab-skill-dotnet = .NET
# kind=name
vocab-skill-ecommerce = E-commerce / Retail
# kind=name
vocab-skill-elasticsearch = Elasticsearch
# kind=name
vocab-skill-experimentation = Experimentation / A-B Testing
# kind=name
vocab-skill-fine-tuning = Fine-tuning
# kind=name
vocab-skill-flink = Flink
# kind=name
vocab-skill-foundation-models = Foundation Models
# kind=name same-as=vocab-sector-gaming
vocab-skill-gaming = Gaming
# kind=name
vocab-skill-gcp = GCP
# kind=name
vocab-skill-generative-ai = Generative AI
# kind=name
vocab-skill-golang = Go
# kind=name
vocab-skill-graphql = GraphQL
# kind=name
vocab-skill-grpc = gRPC
# kind=name
vocab-skill-healthcare = Healthcare
# kind=name
vocab-skill-high-availability = High Availability
# kind=name
vocab-skill-hiring = Hiring / Team Building
# kind=name
vocab-skill-inference = Inference / Serving
# kind=name
vocab-skill-java = Java
# kind=name
vocab-skill-javascript = JavaScript
# kind=name
vocab-skill-jax = JAX
# kind=name
vocab-skill-kafka = Kafka
# kind=name
vocab-skill-kotlin = Kotlin
# kind=name
vocab-skill-kubernetes = Kubernetes
# kind=name
vocab-skill-linux = Linux
# kind=name
vocab-skill-llm = LLMs
# kind=name
vocab-skill-low-latency = Low Latency
# kind=name
vocab-skill-machine-learning = Machine Learning
# kind=name
vocab-skill-mcp = MCP
# kind=name
vocab-skill-mentorship = Mentorship
# kind=name
vocab-skill-microservices = Microservices
# kind=name
vocab-skill-mlops = MLOps
# kind=name
vocab-skill-model-eval = Model Evaluation
# kind=name
vocab-skill-model-training = Model Training
# kind=name
vocab-skill-mysql = MySQL
# kind=name
vocab-skill-nlp = NLP
# kind=name
vocab-skill-nodejs = Node.js
# kind=name
vocab-skill-objective-c = Objective-C
# kind=name
vocab-skill-observability = Observability
# kind=name
vocab-skill-payments = Payments / Fintech
# kind=name
vocab-skill-people-management = People Management
# kind=name
vocab-skill-postgres = PostgreSQL
# kind=name
vocab-skill-project-management = Project Management
# kind=name
vocab-skill-pyspark = PySpark
# kind=name
vocab-skill-python = Python
# kind=name
vocab-skill-pytorch = PyTorch
# kind=name
vocab-skill-r-lang = R
# kind=name
vocab-skill-rag = RAG
# kind=name
vocab-skill-ray = Ray
# kind=name
vocab-skill-react = React
# kind=name
vocab-skill-recommendation = Recommendation Systems
# kind=name
vocab-skill-redis = Redis
# kind=name
vocab-skill-rl = Reinforcement Learning
# kind=name
vocab-skill-rlhf = RLHF
# kind=name
vocab-skill-roadmap = Roadmapping
# kind=name
vocab-skill-robotics-av = Robotics / Autonomous Systems
# kind=name
vocab-skill-ruby = Ruby
# kind=name
vocab-skill-rust = Rust
# kind=name
vocab-skill-scala = Scala
# kind=name
vocab-skill-search-ranking = Search / Ranking
# kind=name
vocab-skill-snowflake = Snowflake
# kind=name
vocab-skill-social-media = Social Media
# kind=name
vocab-skill-spark = Spark
# kind=name
vocab-skill-sql = SQL
# kind=name
vocab-skill-sre = SRE / Reliability
# kind=name
vocab-skill-stakeholder-mgmt = Stakeholder Management
# kind=name
vocab-skill-swift = Swift
# kind=name
vocab-skill-technical-leadership = Technical Leadership
# kind=name
vocab-skill-tensorflow = TensorFlow
# kind=name
vocab-skill-terraform = Terraform
# kind=name
vocab-skill-threat-modeling = Threat Modeling
# kind=name
vocab-skill-transformers = Transformers
# kind=name
vocab-skill-typescript = TypeScript
# kind=name
vocab-skill-vector-db = Vector Databases

## Section headings RoleBand writes itself when a posting names none
## (backend/tracker/connectors/detail: the preamble, the pay block). Every
## other heading is the employer's, shown as written.
# kind=heading wording=as-is
vocab-section-job-description = Job description
# kind=heading wording=as-is
vocab-section-compensation = Compensation

## The basis a pay figure is stated on: DisclosureTrendsResponse.basis
# kind=label note="Names the pay a band states: Median published base salary band"
vocab-pay-basis-base = base salary
