# Project Swift System Workflow Diagrams

These diagrams describe the current Project Swift modules and the sales inquiry workflow implemented across `app/main.py`, API routes, services, repositories, `data.py`, and `app/crews`.

## Sequence Diagrams

### Email Ingestion

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant Listener as Email Listener or CloudMailin
    participant EmailsRoute as emails.py API Route
    participant Parser as email_parser.py
    participant EmailService as EmailService
    participant Spam as HybridSpamFilter
    participant Repo as StateRepository
    participant DraftService as DraftService
    participant Dispatcher as email_dispatcher.py
    participant SMTP as SMTP Server

    Customer->>Listener: Sends product pricing or availability inquiry
    Listener->>EmailsRoute: POST /api/emails/ingest, /receive, or /cloudmailin
    alt CloudMailin webhook
        EmailsRoute->>EmailsRoute: Verify Basic Auth credentials
    end
    EmailsRoute->>Parser: Normalize JSON, form, CloudMailin, or RFC822 payload
    Parser-->>EmailsRoute: IncomingEmail
    EmailsRoute->>EmailService: ingest_email(email) or process_email(email)
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
        DraftService-->>EmailService: DraftResponse
        alt supported inquiry with pending draft
            EmailService->>Repo: upsert_email(status = processed, draft_id)
            EmailService-->>EmailsRoute: Draft queued for review
        else blocked unsupported inquiry
            EmailService->>Dispatcher: send_bad_attempt_response(recipient, subject)
            Dispatcher->>SMTP: Send automatic bad-attempt response when configured
            Dispatcher-->>EmailService: EmailDispatchResult
            EmailService->>Repo: upsert_email(status = auto_replied or received)
            EmailService-->>EmailsRoute: No pending draft created
        end
    end
```

### Draft Generation

```mermaid
sequenceDiagram
    autonumber
    participant EmailService as EmailService
    participant DraftService as DraftService
    participant Workflow as sales_inquiry_crew.py
    participant Processor as SalesProcessingAgent
    participant Products as ProductLookupClient
    participant Drafter as EmailDraftingAgent or Agent Backend
    participant DataFacade as data.py Draft Facade
    participant Repo as StateRepository
    participant Stream as /stream SSE
    participant UI as Sales Officer UI

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
    alt pending draft
        DataFacade->>Stream: publish_event(draft_created)
        Stream-->>UI: draft_created
    else blocked draft
        DataFacade-->>DraftService: Stored blocked workflow row or fallback draft_id
    end
    DraftService-->>EmailService: DraftResponse
```

### Draft Review, Regeneration, and Approval

```mermaid
sequenceDiagram
    autonumber
    actor Officer as Sales Officer
    participant UI as Sales Officer UI
    participant DraftsRoute as drafts.py API Route
    participant DraftService as DraftService
    participant Workflow as sales_inquiry_crew.py
    participant DataFacade as data.py Draft Facade
    participant Repo as StateRepository
    participant Dispatcher as email_dispatcher.py
    participant SMTP as SMTP Server
    participant Stream as /stream SSE
    participant AuditPage as Audit UI

    Officer->>UI: Opens pending queue
    UI->>DraftsRoute: GET /api/drafts or /pending
    DraftsRoute->>DraftService: list_drafts()
    DraftService->>DataFacade: get_drafts()
    DataFacade->>Repo: list_drafts()
    Repo-->>UI: Pending draft queue

    alt Officer edits draft
        Officer->>UI: Updates draft text
        UI->>DraftsRoute: PATCH /api/drafts/{draft_id}
        DraftsRoute->>DraftService: update_draft(draft_id, ai_draft, approver)
        DraftService->>Repo: upsert_draft(updated draft)
        DraftService->>Repo: insert_audit(action = edited)
        DraftService->>Stream: publish_event(draft_updated)
        Stream-->>UI: draft_updated
    else Officer rejects and regenerates draft
        Officer->>UI: Submits reviewer feedback
        UI->>DraftsRoute: POST /api/drafts/{draft_id}/reject
        DraftsRoute->>DraftService: reject_draft(draft_id, reason, approver)
        DraftService->>Workflow: run_sales_inquiry_workflow(IncomingEmail)
        Workflow-->>DraftService: Regenerated SalesWorkflowResult
        DraftService->>Repo: upsert_draft(regenerated pending version)
        DraftService->>Repo: insert_audit(action = rejected)
        DraftService->>Stream: publish_event(regenerated)
        Stream-->>UI: regenerated
    else Officer approves draft
        Officer->>UI: Approves response
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
        Stream-->>UI: draft_approved
    end

    AuditPage->>Repo: list_audits()
    Repo-->>AuditPage: Decision history
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

This diagram includes production classes and data models that have at least one
direct relationship with another class in the diagram. It excludes test-only
classes, private helpers, route functions, module-level workflow functions, and
isolated utility classes that would not add a class-to-class relation.

```mermaid
classDiagram
    direction LR

    class AppSettings {
        +storage_backend: str
        +database_url: str
        +agent_backend: str
        +smtp_configured
        +smtp_from_address
        +public_dict()
    }

    class IncomingEmail {
        +sender: str
        +subject: str
        +body: str
    }

    class EmailPayload {
        +sender: str
        +subject: str
        +body: str
        +conversation_context: str
    }

    class DraftUpdatePayload {
        +ai_draft: str
    }

    class DraftResponse {
        +draft_id: str
        +sender: str
        +subject: str
        +customer_inquiry: str
        +ai_draft: str
        +status: str
    }

    class Draft {
        +draft_id: str
        +sender: str
        +subject: str
        +status: str
        +revisions: int
        +thread_history: list
        +to_dict()
    }

    class EmailService {
        +repository: StateRepository
        +draft_service: DraftGenerator
        +bad_attempt_responder: BadAttemptResponder
        +spam_filter: SpamFilter
        +process_email(email)
        +ingest_email(email)
        +get_queue()
        +reprocess(email_id)
    }

    class DraftGenerator {
        <<interface>>
        +generate_draft(email)
    }

    class BadAttemptResponder {
        <<interface>>
        +__call__(recipient, subject)
    }

    class DraftService {
        +repository: StateRepository
        +generate_draft(email)
        +list_drafts()
        +get_draft(draft_id)
        +update_draft(draft_id, ai_draft)
        +approve_draft(draft_id)
        +reject_draft(draft_id, reason)
    }

    class AuditService {
        +repository: StateRepository
        +create_audit(actor, action, target_type, target_id)
        +list_audits()
        +get_audit(audit_id)
    }

    class AuditLogger {
        +audit_sink: AuditLogSink
        +table_name: str
        +save(log_data)
    }

    class AuditLogSink {
        <<interface>>
        +insert(table_name, row)
    }

    class StateRepository {
        <<interface>>
        +initialize()
        +list_drafts()
        +get_draft(draft_id)
        +upsert_draft(draft)
        +delete_draft(draft_id)
        +list_audits()
        +insert_audit(audit)
        +list_emails()
        +get_email(email_id)
        +upsert_email(email)
        +list_users()
        +get_user_by_username(username)
        +upsert_user(user)
        +find_thread(sender, subject)
        +insert_thread_message(message)
        +get_setting(key)
        +upsert_setting(setting)
    }

    class MemoryStateRepository {
        +_drafts: dict
        +_audits: dict
        +_emails: dict
        +_users: dict
    }

    class PostgresStateRepository {
        +database_url: str
        +initialize()
    }

    class DraftRepository {
        +repository: StateRepository
        +list()
        +get(draft_id)
        +save(draft)
        +delete(draft_id)
    }

    class AuditRepository {
        +repository: StateRepository
        +list()
        +get(audit_id)
        +insert(audit)
    }

    class SalesOfficerAccount {
        +username: str
        +email: str
        +name: str
        +level: str
        +can_view_all_pages
        +public_dict()
    }

    class SpamFilter {
        <<interface>>
        +assess(email)
    }

    class HybridSpamFilter {
        +classifier: TfidfSpamClassifier
        +spam_threshold: float
        +suspected_threshold: float
        +assess(email)
    }

    class TfidfSpamClassifier {
        +pipeline: object
        +available
        +from_builtin_training_data()
        +predict_spam_score(text)
    }

    class SpamAssessment {
        +is_spam: bool
        +score: float
        +action: str
        +reasons: list
        +classifier_score: float
    }

    class EmailPreprocessor {
        +noise_filter: StructuralNoiseFilter
        +relevance_selector: InquiryLineSelector
        +preprocess(email)
    }

    class StructuralNoiseFilter {
        +remove(body)
    }

    class InquiryLineSelector {
        +select(lines)
    }

    class PreprocessedEmail {
        +email: IncomingEmail
        +original_body: str
        +removed_lines: list
        +changed
    }

    class FilteredEmailLines {
        +kept: list
        +removed: list
    }

    class CustomerInquiryGuardrail {
        +rules: tuple
        +assess(text)
    }

    class GuardrailRule {
        +flag: str
        +patterns: tuple
    }

    class GuardrailAssessment {
        +flags: list
        +blocked
    }

    class SalesProcessingAgent {
        +product_client: ProductLookupClient
        +extract_inquiry(sender, subject, body)
        +get_product_context(query)
        +lookup_product_context(product_name, query)
        +lookup_product_list_context(query)
        +detect_risks(text)
    }

    class EmailDraftingAgent {
        +generate(info)
        +generate_response(inquiry, product_context)
        +validate_draft(inquiry, product_context, draft)
    }

    class ProductLookupClient {
        <<interface>>
        +get_product(query)
    }

    class PostgresProductLookupClient {
        +database_url: str
        +get_product(query)
        +search_products(query, limit)
        +suggest_products(query, limit)
    }

    class InquiryDetails {
        +sender: str
        +subject: str
        +body: str
        +inquiry_type: str
        +product_name: str
        +quantity: int
        +risk_flags: list
        +confidence: float
    }

    class ProductOption {
        +product: str
        +sku: str
        +source_url: str
        +stock_availability: int
        +price: float
        +confidence: float
    }

    class ProductContext {
        +product: str
        +sku: str
        +source_url: str
        +stock_availability: int
        +price: float
        +currency: str
        +suggested_products: list
        +listed_products: list
    }

    class DraftValidationResult {
        +valid: bool
        +action: str
        +reasons: list
    }

    class SalesWorkflowResult {
        +draft_id: str
        +sender: str
        +subject: str
        +customer_inquiry: str
        +inquiry: InquiryDetails
        +product_context: ProductContext
        +ai_draft: str
        +validation: DraftValidationResult
        +status: str
        +supervisor_review: DraftValidationResult
    }

    class EmailDispatchResult {
        +sent: bool
        +recipient: str
        +error: str
        +reply_to: str
    }

    EmailService o-- StateRepository : persists intake
    EmailService o-- DraftGenerator : generates drafts
    EmailService o-- BadAttemptResponder : blocked response
    EmailService o-- SpamFilter : spam assessment
    EmailService ..> IncomingEmail : accepts
    EmailService ..> EmailPayload : creates
    EmailService ..> DraftResponse : returns
    EmailService ..> EmailPreprocessor : cleans email
    EmailService ..> EmailDispatchResult : reports auto reply

    DraftGenerator <|.. DraftService
    DraftService o-- StateRepository : review state
    DraftService ..> EmailPayload : accepts
    DraftService ..> DraftResponse : returns
    DraftService ..> DraftUpdatePayload : edit payload
    DraftService ..> Draft : maps review rows
    DraftService ..> SalesWorkflowResult : persists workflow
    DraftService ..> EmailDispatchResult : approval dispatch
    DraftService ..> SalesOfficerAccount : reviewer identity

    AuditService o-- StateRepository : audit store
    DraftRepository o-- StateRepository : legacy wrapper
    AuditRepository o-- StateRepository : legacy wrapper
    AuditLogger o-- AuditLogSink : writes through

    StateRepository <|.. MemoryStateRepository
    StateRepository <|.. PostgresStateRepository
    PostgresStateRepository ..> AppSettings : database config
    StateRepository ..> SalesOfficerAccount : user rows

    SpamFilter <|.. HybridSpamFilter
    HybridSpamFilter o-- TfidfSpamClassifier : optional model
    HybridSpamFilter ..> IncomingEmail : scans
    HybridSpamFilter ..> SpamAssessment : returns

    EmailPreprocessor *-- StructuralNoiseFilter : removes noise
    EmailPreprocessor *-- InquiryLineSelector : selects inquiry
    EmailPreprocessor ..> IncomingEmail : accepts
    EmailPreprocessor ..> PreprocessedEmail : returns
    StructuralNoiseFilter ..> FilteredEmailLines : returns
    PreprocessedEmail *-- IncomingEmail : cleaned email

    CustomerInquiryGuardrail o-- GuardrailRule : evaluates rules
    CustomerInquiryGuardrail ..> GuardrailAssessment : returns
    SalesProcessingAgent ..> CustomerInquiryGuardrail : risk checks

    SalesProcessingAgent o-- ProductLookupClient : product facts
    ProductLookupClient <|.. PostgresProductLookupClient
    PostgresProductLookupClient ..> AppSettings : database config
    SalesProcessingAgent ..> InquiryDetails : extracts
    SalesProcessingAgent ..> ProductContext : creates
    SalesProcessingAgent ..> ProductOption : suggestions

    EmailDraftingAgent ..> InquiryDetails : uses
    EmailDraftingAgent ..> ProductContext : uses
    EmailDraftingAgent ..> DraftValidationResult : returns

    SalesWorkflowResult *-- InquiryDetails : inquiry
    SalesWorkflowResult *-- ProductContext : product context
    SalesWorkflowResult *-- DraftValidationResult : validation
    ProductContext o-- ProductOption : product lists
    BadAttemptResponder ..> EmailDispatchResult : returns
```

## Activity Diagrams

### Submit and Ingest Email

```mermaid
flowchart TD
    start([Start])
    receive[Receive email from JSON, form, RFC822, or CloudMailin]
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
    requestDraft[Request draft generation]
    draftStatus{Draft status pending?}
    processed[Persist email status processed with draft_id]
    blocked[Persist email status auto_replied or received]
    queued[Return queued draft response]
    unsupported[Return unsupported-request response]
    stop([End])

    start --> receive --> auth
    auth -- Yes --> verify --> authOk
    authOk -- No --> rejectAuth --> stop
    authOk -- Yes --> parse
    auth -- No --> parse
    parse --> preprocess --> persistReceived --> spam --> spamDecision
    spamDecision -- Block --> spamStore --> noDraft --> stop
    spamDecision -- Review --> spamStore --> noDraft --> stop
    spamDecision -- Allow --> requestDraft --> draftStatus
    draftStatus -- Yes --> processed --> queued --> stop
    draftStatus -- No --> blocked --> unsupported --> stop
```

### Generate Sales Draft

```mermaid
flowchart TD
    start([Start])
    generate[Receive draft generation request]
    context[Build conversation context from prior audits]
    extract[Extract inquiry type, product, quantity, delivery, risks]
    supportedIntent{Pricing or availability inquiry?}
    blockUnsupported[Create blocked draft response]
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
    persistBlocked[Persist blocked workflow result]
    returnBlocked[Return unsupported-request response]
    stop([End])

    start --> generate --> context --> extract --> supportedIntent
    supportedIntent -- No --> blockUnsupported --> persistBlocked --> autoReply --> returnBlocked --> stop
    supportedIntent -- Yes --> productLookup --> backend
    backend -- external --> external --> draft
    backend -- crewai --> crewai --> draft
    backend -- deterministic --> deterministic --> draft
    draft --> validate --> supported
    supported -- Yes --> persistDraft --> publishCreated --> returnQueued --> stop
    supported -- No --> persistBlocked --> autoReply
```

### Review and Edit Draft

```mermaid
flowchart TD
    start([Start])
    review[Sales officer opens pending queue]
    action{Reviewer action}
    edit[Edit draft text]
    persistEdit[Persist updated pending draft]
    auditEdit[Insert edited audit]
    publishEdit[Publish draft_updated SSE event]
    continueReview[Return updated draft to pending queue]
    stop([End])

    start --> review --> action
    action -- Edit --> edit --> persistEdit --> auditEdit --> publishEdit --> continueReview --> stop
    action -- No edit --> stop
```

### Reject and Regenerate Draft

```mermaid
flowchart TD
    start([Start])
    review[Sales officer reviews pending draft]
    reject[Reject draft with feedback]
    loadDraft[Load current draft and previous AI response]
    context[Build conversation context from prior audits]
    regenerate[Regenerate through workflow with reviewer feedback]
    validate[Validate regenerated response and guardrails]
    persistRegen[Persist regenerated pending version]
    auditReject[Insert rejected audit]
    publishRegen[Publish regenerated SSE event]
    returnReview[Return regenerated draft to pending queue]
    stop([End])

    start --> review --> reject --> loadDraft --> context --> regenerate
    regenerate --> validate --> persistRegen --> auditReject --> publishRegen --> returnReview --> stop
```

### Approve and Send Draft

```mermaid
flowchart TD
    start([Start])
    review[Sales officer reviews pending draft]
    approve[Approve draft]
    send[Send approved reply through SMTP if configured]
    sent{Delivery accepted or SMTP skipped?}
    auditApprove[Insert approved audit]
    auditFailed[Insert approval_failed audit]
    removeDraft[Delete approved draft from pending queue]
    keepDraft[Keep draft pending for retry]
    publishApprove[Publish draft_approved SSE event]
    publishFailure[Return approval failure]
    stop([End])

    start --> review --> approve --> send --> sent
    sent -- Yes --> auditApprove --> removeDraft --> publishApprove --> stop
    sent -- No --> auditFailed --> keepDraft --> publishFailure --> stop
```

### Operator Views and Maintenance

```mermaid
flowchart TD
    start([Start])
    useCase{Operator use case}
    dashboard[View dashboard]
    audit[View audit history]
    queue[Inspect email queue]
    reprocess[Reprocess stored email]
    health[Check service health]
    catalog[Import or query product catalog]
    readRepo[Read repository state]
    regenerate[Generate draft from stored email]
    catalogRepo[Read or write product catalog rows]
    returnView[Return current state]
    stop([End])

    start --> useCase
    useCase -- Dashboard --> dashboard --> readRepo --> returnView --> stop
    useCase -- Audit history --> audit --> readRepo
    useCase -- Email queue --> queue --> readRepo
    useCase -- Reprocess email --> reprocess --> regenerate --> returnView
    useCase -- Health --> health --> returnView
    useCase -- Product catalog --> catalog --> catalogRepo --> returnView
```
