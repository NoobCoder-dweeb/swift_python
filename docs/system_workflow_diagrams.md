# Project Swift System Workflow Diagrams

These diagrams describe the current Project Swift modules and the sales inquiry workflow implemented across `app/main.py`, API routes, services, repositories, `data.py`, and `app/crews`.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant Listener as Email Listener or UI Client
    participant EmailsRoute as emails.py API Route
    participant Parser as email_parser.py
    participant EmailService as EmailService
    participant Spam as HybridSpamFilter
    participant Repo as StateRepository
    participant DraftService as DraftService
    participant Workflow as sales_inquiry_crew.py
    participant Processor as SalesProcessingAgent
    participant Products as ProductLookupClient
    participant Drafter as EmailDraftingAgent or Agent Backend
    participant DataFacade as data.py Draft Facade
    participant UI as Sales Officer UI
    participant DraftsRoute as drafts.py API Route
    participant Dispatcher as email_dispatcher.py
    participant SMTP as SMTP Server
    participant Audit as AuditService or Repository
    participant Stream as /stream SSE

    Customer->>Listener: Sends product pricing or availability inquiry
    Listener->>EmailsRoute: POST /api/emails/ingest, /receive, or /cloudmailin
    alt CloudMailin webhook
        EmailsRoute->>EmailsRoute: Verify Basic Auth credentials
    end
    EmailsRoute->>Parser: Normalize JSON, form, CloudMailin, or RFC822 payload
    Parser-->>EmailsRoute: IncomingEmail
    EmailsRoute->>EmailService: ingest_email(email)
    EmailService->>EmailService: preprocess_email(email)
    EmailService->>Repo: upsert_email(status = received)
    EmailService->>Spam: assess(email)
    Spam-->>EmailService: SpamAssessment

    alt spam blocked or suspected spam
        EmailService->>Repo: upsert_email(status = spam or suspected_spam)
        EmailService-->>EmailsRoute: No draft created
        EmailsRoute-->>Listener: Spam review or block response
    else allowed inquiry
        EmailService->>DraftService: generate_draft(EmailPayload)
        DraftService->>Workflow: run_sales_inquiry_workflow(IncomingEmail)
        Workflow->>Processor: extract_inquiry(sender, subject, body)
        Processor->>Processor: detect intent, quantity, delivery, guardrail risks
        Workflow->>Products: lookup approved product context
        Products-->>Workflow: ProductContext
        alt external agent backend configured
            Workflow->>Drafter: Request external draft
        else CrewAI backend configured
            Workflow->>Drafter: Run multi-agent extraction, drafting, validation
        else deterministic default
            Workflow->>Drafter: Generate local deterministic response
        end
        Drafter-->>Workflow: Draft text
        Workflow->>Workflow: validate draft and assign pending or blocked status
        Workflow-->>DraftService: SalesWorkflowResult
        DraftService->>DataFacade: add_generated_draft(...)
        DataFacade->>Repo: find_draft or upsert_draft
        DataFacade->>Stream: publish_event(draft_created)
        DraftService-->>EmailService: DraftResponse

        alt supported inquiry with pending draft
            EmailService->>Repo: upsert_email(status = processed, draft_id)
            EmailService-->>EmailsRoute: Draft queued for review
            UI->>DraftsRoute: GET /api/drafts or /pending
            DraftsRoute->>DraftService: list_drafts()
            DraftService->>DataFacade: get_drafts()
            DataFacade->>Repo: list_drafts()
            Repo-->>UI: Pending draft queue
        else blocked unsupported inquiry
            EmailService->>Dispatcher: send_bad_attempt_response(recipient, subject)
            Dispatcher->>SMTP: Send automatic bad-attempt response when configured
            Dispatcher-->>EmailService: EmailDispatchResult
            EmailService->>Repo: upsert_email(status = auto_replied or received)
        end
    end

    alt Sales officer edits draft
        UI->>DraftsRoute: PATCH /api/drafts/{draft_id}
        DraftsRoute->>DraftService: update_draft(draft_id, ai_draft, approver)
        DraftService->>Repo: upsert_draft(updated draft)
        DraftService->>Repo: insert_audit(action = edited)
        DraftService->>Stream: publish_event(draft_updated)
    else Sales officer rejects draft
        UI->>DraftsRoute: POST /api/drafts/{draft_id}/reject
        DraftsRoute->>DraftService: reject_draft(draft_id, reason, approver)
        DraftService->>Workflow: run_sales_inquiry_workflow(... reviewer_feedback ...)
        Workflow-->>DraftService: Regenerated SalesWorkflowResult
        DraftService->>Repo: upsert_draft(regenerated pending version)
        DraftService->>Repo: insert_audit(action = rejected)
        DraftService->>Stream: publish_event(regenerated)
    else Sales officer approves draft
        UI->>DraftsRoute: POST /api/drafts/{draft_id}/approve
        DraftsRoute->>DraftService: approve_draft(draft_id, approver)
        DraftService->>DataFacade: approve_draft(...)
        DataFacade->>Dispatcher: send_approved_draft(recipient, subject, body)
        Dispatcher->>SMTP: Send approved customer reply when configured
        SMTP-->>Dispatcher: Accepted or failed
        Dispatcher-->>DataFacade: EmailDispatchResult
        DataFacade->>Repo: insert_audit(action = approved or failed)
        DataFacade->>Repo: delete_draft(draft_id) when approved
        DataFacade->>Stream: publish_event(draft_approved)
    end

    UI->>Stream: Subscribe to /stream
    Stream-->>UI: draft_created, draft_updated, regenerated, approved events
    UI->>Audit: GET /api/audits or /audit
    Audit->>Repo: list_audits()
    Repo-->>UI: Decision history
```

## Use Case Diagram

Mermaid does not have a dedicated UML use-case renderer, so this uses Mermaid flowchart syntax with actors and oval use cases.

```mermaid
flowchart LR
    customer[Customer]
    listener[Email Listener or CloudMailin]
    officer[Sales Officer]
    manager[Sales Manager or Admin]
    externalAgent[External Agent or CrewAI]
    smtp[SMTP Provider]
    postgres[(PostgreSQL)]

    subgraph ProjectSwift[Project Swift Sales Inquiry System]
        UC1([Submit customer inquiry])
        UC2([Normalize incoming email])
        UC3([Verify CloudMailin webhook])
        UC4([Preprocess email body])
        UC5([Classify spam])
        UC6([Generate sales draft])
        UC7([Extract inquiry details])
        UC8([Lookup product facts])
        UC9([Validate draft and guardrails])
        UC10([Queue pending draft])
        UC11([Review pending drafts])
        UC12([Edit AI draft])
        UC13([Reject and regenerate draft])
        UC14([Approve draft])
        UC15([Send approved reply])
        UC16([Send unsupported-request auto reply])
        UC17([Record audit trail])
        UC18([View dashboard])
        UC19([View audit history])
        UC20([Reprocess stored email])
        UC21([Stream live UI updates])
        UC22([Check service health])
        UC23([Import or query product catalog])
    end

    customer --> UC1
    listener --> UC1
    listener --> UC3
    UC1 --> UC2
    UC3 --> UC2
    UC2 --> UC4
    UC4 --> UC5
    UC5 --> UC6
    UC6 --> UC7
    UC7 --> UC8
    UC8 --> UC9
    UC9 --> UC10
    UC9 --> UC16
    UC10 --> UC21

    officer --> UC11
    officer --> UC12
    officer --> UC13
    officer --> UC14
    officer --> UC18
    officer --> UC20
    UC12 --> UC17
    UC13 --> UC6
    UC13 --> UC17
    UC14 --> UC15
    UC14 --> UC17
    UC15 --> smtp
    UC16 --> smtp

    manager --> UC18
    manager --> UC19
    manager --> UC22

    UC6 --> externalAgent
    UC8 --> UC23
    UC10 --> postgres
    UC17 --> postgres
    UC20 --> postgres
    UC23 --> postgres
```

## Class Diagram

```mermaid
classDiagram
    direction LR

    class AppSettings {
        +storage_backend
        +database_url
        +ui_enabled
        +agent_backend
        +smtp_configured
        +cloudmailin_auth_configured
        +public_dict()
    }

    class IncomingEmail {
        +sender
        +subject
        +body
    }

    class EmailPayload {
        +sender
        +subject
        +body
        +conversation_context
    }

    class DraftResponse {
        +draft_id
        +sender
        +subject
        +customer_inquiry
        +ai_draft
        +status
    }

    class DraftUpdatePayload {
        +ai_draft
    }

    class SalesOfficerAccount {
        +username
        +name
        +role
        +initials
        +can_view_all_pages
        +public_dict()
    }

    class EmailService {
        +process_email(email)
        +ingest_email(email)
        +get_queue()
        +reprocess(email_id)
    }

    class DraftService {
        +generate_draft(email)
        +list_drafts()
        +get_draft(draft_id)
        +update_draft(draft_id, ai_draft)
        +approve_draft(draft_id)
        +reject_draft(draft_id, reason)
    }

    class AuditService {
        +create_audit(actor, action, target_type, target_id)
        +list_audits()
        +get_audit(audit_id)
    }

    class StateRepository {
        <<interface>>
        +initialize()
        +list_drafts()
        +get_draft(draft_id)
        +find_draft(sender, subject, body, status)
        +upsert_draft(draft)
        +delete_draft(draft_id)
        +list_audits()
        +get_audit(audit_id)
        +find_audit(draft_id, action)
        +insert_audit(audit)
        +list_emails()
        +get_email(email_id)
        +upsert_email(email)
    }

    class MemoryStateRepository {
        +list_drafts()
        +upsert_draft(draft)
        +insert_audit(audit)
        +upsert_email(email)
    }

    class PostgresStateRepository {
        +database_url
        +initialize()
        +list_drafts()
        +upsert_draft(draft)
        +insert_audit(audit)
        +upsert_email(email)
    }

    class DraftRepository {
        +list()
        +get(draft_id)
        +save(draft)
        +delete(draft_id)
    }

    class Draft {
        +draft_id
        +sender
        +subject
        +body
        +status
        +created
        +updated
        +revisions
        +ai_draft
        +to_dict()
    }

    class SpamFilter {
        <<interface>>
        +assess(email)
    }

    class HybridSpamFilter {
        +assess(email)
    }

    class TfidfSpamClassifier {
        +available
        +from_builtin_training_data()
        +predict_spam_score(text)
    }

    class SpamAssessment {
        +is_spam
        +score
        +action
        +reasons
        +classifier_score
    }

    class CustomerInquiryGuardrail {
        +assess(text)
    }

    class GuardrailAssessment {
        +flags
        +blocked
    }

    class SalesInquiryWorkflow {
        +run_sales_inquiry_workflow(email)
        +run_sales_inquiry_crew(sender, subject, body)
    }

    class SalesProcessingAgent {
        +extract_inquiry(sender, subject, body)
        +get_product_context(query)
        +lookup_product_context(product_name, query)
    }

    class EmailDraftingAgent {
        +generate_response(inquiry, product_context)
        +validate_draft(inquiry, product_context, draft)
    }

    class ProductLookupClient {
        <<interface>>
        +get_product(query)
    }

    class PostgresProductLookupClient {
        +database_url
        +get_product(query)
        +search_products(query)
        +suggest_products(query)
    }

    class LocalLLMConfig {
        +model
        +provider
        +base_url
        +timeout
        +temperature
        +from_env()
        +for_role(role, default_model)
    }

    class MultiAgentLLMConfig {
        +supervisor
        +sales
        +drafting
        +from_env()
        +validate_unique_models()
        +model_names()
    }

    class InquiryDetails {
        +sender
        +subject
        +body
        +inquiry_type
        +product_name
        +quantity
        +requested_delivery
        +missing_information
        +risk_flags
        +confidence
    }

    class ProductContext {
        +product
        +sku
        +source_url
        +stock_availability
        +price
        +currency
        +lead_time_days
        +confidence
        +notes
    }

    class ProductOption {
        +product
        +sku
        +category
        +stock_availability
        +price
        +confidence
    }

    class DraftValidationResult {
        +valid
        +action
        +reasons
    }

    class SalesWorkflowResult {
        +draft_id
        +sender
        +subject
        +customer_inquiry
        +ai_draft
        +status
        +execution_mode
        +learning_notes
        +chokeholds
        +elapsed_ms
    }

    class EmailDispatchResult {
        +sent
        +recipient
        +error
        +reply_to
    }

    AppSettings <.. EmailService : settings
    IncomingEmail --> EmailService : input
    EmailPayload --> DraftService : input
    DraftUpdatePayload --> DraftService : update
    DraftResponse <-- DraftService : returns

    EmailService --> StateRepository : persists emails
    EmailService --> DraftService : generates drafts
    EmailService --> SpamFilter : spam assessment
    EmailService ..> EmailDispatchResult : blocked auto reply

    DraftService --> StateRepository : drafts and audits
    DraftService --> SalesInquiryWorkflow : runs workflow
    DraftService ..> Draft : data facade model
    AuditService --> StateRepository : audit storage
    DraftRepository --> StateRepository : wrapper

    StateRepository <|.. MemoryStateRepository
    StateRepository <|.. PostgresStateRepository

    SpamFilter <|.. HybridSpamFilter
    HybridSpamFilter --> TfidfSpamClassifier : optional model
    HybridSpamFilter --> SpamAssessment : returns

    SalesInquiryWorkflow --> SalesProcessingAgent : extracts context
    SalesInquiryWorkflow --> EmailDraftingAgent : drafts response
    SalesInquiryWorkflow --> ProductLookupClient : product facts
    SalesInquiryWorkflow --> InquiryDetails
    SalesInquiryWorkflow --> ProductContext
    SalesInquiryWorkflow --> DraftValidationResult
    SalesInquiryWorkflow --> SalesWorkflowResult
    SalesInquiryWorkflow --> MultiAgentLLMConfig : optional CrewAI

    ProductLookupClient <|.. PostgresProductLookupClient
    SalesProcessingAgent --> CustomerInquiryGuardrail : risk detection
    CustomerInquiryGuardrail --> GuardrailAssessment : returns
    ProductContext "1" o-- "*" ProductOption : suggestions
    MultiAgentLLMConfig o-- LocalLLMConfig : role models
    SalesWorkflowResult --> InquiryDetails
    SalesWorkflowResult --> ProductContext
    SalesWorkflowResult --> DraftValidationResult
    SalesOfficerAccount ..> DraftService : approver identity
```

## Activity Diagram

```mermaid
flowchart TD
    start([Start])
    receive[Receive email from JSON, form, RFC822, CloudMailin, or UI]
    auth{CloudMailin endpoint?}
    verify[Verify Basic Auth]
    authOk{Credentials valid?}
    rejectAuth[Return 401 or 503]
    parse[Parse and normalize into IncomingEmail]
    preprocess[Preprocess body and remove boilerplate]
    persistReceived[Persist email with status received]
    spam[Assess spam with rules and optional TF-IDF model]
    spamDecision{Spam action}
    spamStore[Persist status spam or suspected_spam]
    noDraft[Return without creating a draft]

    generate[Generate draft request]
    context[Build conversation context from prior audits]
    extract[Extract inquiry type, product, quantity, delivery, risks]
    productLookup[Lookup approved product catalog facts]
    backend{Agent backend}
    external[Call external agent service]
    crewai[Run CrewAI agents]
    deterministic[Use deterministic local drafter]
    draft[Create draft response]
    validate[Validate response and guardrails]
    supported{Status pending?}
    persistDraft[Persist pending draft]
    publishCreated[Publish draft_created SSE event]
    returnQueued[Return queued draft response]

    autoReply[Send bad-attempt response when SMTP allows]
    persistBlocked[Persist email status auto_replied or received]
    returnBlocked[Return unsupported-request response]

    review[Sales officer opens pending queue]
    action{Reviewer action}
    edit[Edit draft text]
    auditEdit[Insert edited audit]
    publishEdit[Publish draft_updated SSE event]
    approve[Approve draft]
    send[Send approved reply through SMTP if configured]
    auditApprove[Insert approved or failed audit]
    removeDraft[Delete approved draft from pending queue]
    publishApprove[Publish approved SSE event]
    reject[Reject draft with feedback]
    regenerate[Regenerate through workflow with reviewer feedback]
    auditReject[Insert rejected audit]
    publishRegen[Publish regenerated SSE event]
    dashboard[Dashboard and audit pages read repository state]
    stop([End])

    start --> receive
    receive --> auth
    auth -- Yes --> verify --> authOk
    authOk -- No --> rejectAuth --> stop
    authOk -- Yes --> parse
    auth -- No --> parse
    parse --> preprocess --> persistReceived --> spam --> spamDecision
    spamDecision -- Block --> spamStore --> noDraft --> stop
    spamDecision -- Review --> spamStore --> noDraft --> stop
    spamDecision -- Allow --> generate

    generate --> context --> extract --> productLookup --> backend
    backend -- external --> external --> draft
    backend -- crewai --> crewai --> draft
    backend -- deterministic --> deterministic --> draft
    draft --> validate --> supported
    supported -- Yes --> persistDraft --> publishCreated --> returnQueued --> review
    supported -- No --> autoReply --> persistBlocked --> returnBlocked --> stop

    review --> action
    action -- Edit --> edit --> auditEdit --> publishEdit --> review
    action -- Approve --> approve --> send --> auditApprove --> removeDraft --> publishApprove --> dashboard --> stop
    action -- Reject --> reject --> regenerate --> auditReject --> publishRegen --> review
```
