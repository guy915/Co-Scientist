# AI Co-Scientist Clone: Product Information Architecture & Interaction Blueprint

## 1. Information Architecture

### System Overview

The AI Co-Scientist clone follows a **hub-and-spoke architecture** with a central workspace hub connecting to specialized functional modules. The system implements a multi-agent workflow (Generate → Debate → Evolve) accessible through a conversational interface.

### Content Hierarchy

```
Platform Hub (Home)
├── Onboarding & Welcome
├── Research Workspace
│   ├── Goal Creation Flow
│   ├── Interview/Refinement
│   ├── Run Configuration
│   ├── Active Run Monitoring
│   └── Results & Reports
│       ├── Ideas Report
│       ├── Knowledge Base
│       ├── Summary Report
│       └── Detailed Proposals
├── Follow-up Agent Interactions
├── Project Management
│   ├── History/Archive
│   ├── Saved Runs
│   └── Drafts
├── Knowledge Base
├── Settings & Preferences
└── Help & Documentation
```

### Data Flow Architecture

- **Input Layer**: Natural language research goals, user feedback, uploaded documents
- **Processing Layer**: Multi-agent system (Generation, Reflection, Ranking, Evolution, Proximity, Meta-review, Supervisor agents)
- **Output Layer**: Structured reports, hypotheses, knowledge bases, ranked ideas
- **Storage Layer**: Context memory, run history, user preferences, knowledge graph

---

## 2. Screen Inventory

### 2.1 Home/Hub Page

**Purpose**: Central dashboard and entry point for all research activities

**Components**:

- **Header**: Logo, search bar, notifications, user profile
- **Quick Start Section**: "New Research Goal" prominent CTA button
- **Active Runs Panel**: Cards showing ongoing research runs with progress indicators
- **Recent Projects**: List of recent research goals with quick access
- **Templates Gallery**: Pre-built research templates (Drug Discovery, Target Identification, Mechanism Analysis, etc.)
- **Activity Feed**: Recent system updates, completed runs, shared projects
- **Quick Actions**: Import from literature, Continue previous run, Explore knowledge base

**State Variations**:

- **First-time user**: Welcome banner with onboarding CTA
- **Returning user**: Personalized greeting with recent activity
- **Active runs**: Real-time progress indicators in sidebar

---

### 2.2 Onboarding/Welcome Experience

**Purpose**: Introduce new users to the platform capabilities and collect initial preferences

**Components**:

- **Welcome Screen**: Value proposition with animated demo of the workflow
- **Capability Tour**: Interactive walkthrough of key features:
    - Multi-agent hypothesis generation
    - Tournament-style evaluation
    - Knowledge base integration
    - Follow-up agent interactions
- **Research Domain Selection**: Pre-configure for user's field (Life Sciences, Materials Science, Physics, etc.)
- **Integration Setup**: Connect external databases (PubMed, ChEMBL, UniProt, etc.)
- **Notification Preferences**: Email alerts for run completion, weekly digests

**Interaction Flow**:

1. Welcome modal with video/demo
2. Interactive feature tour (4-5 steps)
3. Domain and preference selection
4. Optional integration configuration
5. First research goal prompt

---

### 2.3 Research Goal Creation Flow

**Purpose**: Capture user's research challenge and refine through conversational interview

**Components**:

- **Goal Input Modal**: Large text area for research challenge description
- **Conversation Interface**: Chat-style interface with AI assistant
- **Progress Indicators**: Steps showing (Challenge → Focus Area → Preferences → Review)
- **Template Selector**: Pre-built prompts for common research types
- **Voice Input**: Optional speech-to-text for goal input

**Interaction Flow**:

1. **Initial Input**: User enters research challenge in natural language
2. **Clarification Questions**: AI asks follow-up questions to refine:
    - Specific research question
    - Hypotheses to explore/test
    - Focus areas and constraints
    - Preferences (novelty vs. feasibility, breadth vs. depth)
3. **Summarization**: AI presents structured research plan
4. **User Review**: User can edit or approve the plan
5. **Transition to Run Configuration**

**UI States**:

- **Input state**: Empty text area with placeholder examples
- **Processing state**: Typing indicator while AI analyzes input
- **Clarification state**: Chat interface with Q&A
- **Review state**: Structured plan with edit capabilities

---

### 2.4 Interview/Refinement Flow

**Purpose**: Structured conversational interface to build comprehensive research specification

**Components**:

- **Chat Interface**: Full-screen or side-panel chat with agent
- **Context Panel**: Shows current understanding of research goal
- **Structured Form**: Optional tabular view of specifications
- **Suggestion Chips**: Pre-defined options for quick responses
- **File Upload**: Support for uploading relevant papers, datasets

**Key Interview Topics**:

- Research Challenge: Core problem statement
- Focus Area: Specific domains or mechanisms to explore
- Hypotheses: Specific hypotheses to test or explore
- Constraints: Ethical, technical, resource limitations
- Preferences: Output format preferences (NIH format, grant proposal, etc.)

**State Management**:

- Real-time updates to research plan as user provides input
- Visual indication of completion status for each section
- Ability to save as draft and return later

---

### 2.5 Run Configuration

**Purpose**: Configure execution parameters before starting the multi-agent research run

**Components**:

- **Run Type Selection**:
    - **Standard Run**: ~20-30 hypotheses, 2-4 hours, comprehensive analysis
    - **Advanced Run**: ~50+ hypotheses, 6-8 hours, deep exploration with additional agents
- **Agent Configuration**:
    - Toggle specific agents on/off
    - Set agent weights/resource allocation
    - Configure evolution iterations
- **Knowledge Base Settings**:
    - Select integrated databases
    - Upload additional literature
    - Set recency preferences for citations
- **Output Preferences**:
    - Report format (NIH Specific Aims, standard research proposal, etc.)
    - Detail level (Executive summary vs. comprehensive)
    - Citation style
- **Notification Settings**: Email on completion, progress updates

**Confirmation Panel**:

- Summary of configuration
- Estimated time and cost
- Final confirmation button

---

### 2.6 Active Run Monitoring

**Purpose**: Real-time visibility into multi-agent research execution

**Components**:

- **Progress Dashboard**:
    - Overall progress bar with percentage
    - Estimated time remaining
    - Agent activity status indicators
- **Agent Activity Panel**: Live view of which agents are active:
    - Generation Agent: Creating hypotheses
    - Reflection Agent: Reviewing and critiquing
    - Ranking Agent: Running tournaments
    - Evolution Agent: Refining top hypotheses
    - Meta-review Agent: Synthesizing findings
- **Live Log Stream**: Real-time updates of agent actions
- **Knowledge Base Growth**: Visual showing accumulating references
- **Tournament Visualization**: Interactive view of hypothesis competition
    - ELO rating changes
    - Head-to-head match results
    - Debate transcripts
- **Intervention Points**: Ability to:
    - Add user feedback mid-run
    - Pause/resume run
    - Provide additional context
    - Early termination with partial results

**UI States**:

- **Initializing**: Agent setup and task queue creation
- **Running**: Live progress with animated indicators
- **Paused**: Awaiting user input or resumption
- **Completing**: Final synthesis and report generation
- **Completed**: Results ready for review

---

### 2.7 Generated Report Pages

#### 2.7.1 Ideas Report

**Purpose**: Present ranked hypotheses with supporting evidence

**Components**:

- **Executive Summary**: Top 3-5 hypotheses with key points
- **Ranked Hypothesis List**:
    - ELO score and ranking
    - Hypothesis statement
    - Supporting evidence summary
    - Confidence score
    - Novelty assessment
- **Tournament Results**: Visualization of the competition process
- **Debate Transcripts**: Records of agent discussions
- **Comparison Tool**: Side-by-side comparison of multiple hypotheses

#### 2.7.2 Knowledge Base

**Purpose**: Comprehensive literature review with verified references

**Components**:

- **Search Interface**: Full-text search across gathered literature
- **Reference List**: All papers and sources used
    - Title, authors, year
    - Relevance score
    - Citation context
    - Full-text access links
- **Topic Clusters**: Visual map of research themes
- **Citation Network**: Graph showing paper relationships
- **Evidence Table**: Structured extraction of key findings

#### 2.7.3 Summary Report

**Purpose**: High-level overview of research findings

**Components**:

- **Research Goal Recap**: Original challenge and specifications
- **Key Findings**: Synthesized insights
- **Recommended Next Steps**: Actionable research directions
- **Limitations**: Critical flaws and non-viable directions identified
- **Export Options**: PDF, Word, Markdown, LaTeX

#### 2.7.4 Detailed Proposal

**Purpose**: Full research proposal for grant applications or research planning

**Components**:

- **Structured Sections**:
    - Specific Aims (if NIH format)
    - Background and Significance
    - Research Design and Methods
    - Expected Outcomes
    - Timeline and Milestones
- **Citation Management**: Properly formatted references
- **Budget Justification**: Optional section for grant applications

---

### 2.8 Idea Detail View

**Purpose**: Deep dive into individual hypothesis with full reasoning

**Components**:

- **Hypothesis Statement**: Clear, testable formulation
- **Reasoning Chain**: Step-by-step logic supporting the hypothesis
- **Evidence Base**: Specific papers and data points
- **Novelty Assessment**: Comparison to existing research
- **Testability Analysis**: Experimental design suggestions
- **Agent Evolution History**: How the hypothesis was refined through iterations
- **User Notes**: Space for researcher annotations
- **Follow-up Actions**: Links to related ideas or knowledge base entries

---

### 2.9 Knowledge Base Views

**Purpose**: Explore and interact with the accumulated research knowledge

**Components**:

- **Graph Visualization**: Interactive network of papers, concepts, and hypotheses
- **Semantic Search**: Natural language queries across the knowledge base
- **Document Viewer**: Full-text access with annotation tools
- **Citation Context**: See how papers were cited in generated hypotheses
- **Export Tools**: Download subsets of the knowledge base
- **Follow-up Queries**: Ask questions about the accumulated knowledge

---

### 2.10 Follow-up Agent Interaction

**Purpose**: Continue refinement and exploration based on initial results

**Components**:

- **Chat Interface**: Natural language conversation with follow-up agent
- **Context Panel**: Reference to original run and current findings
- **Action Menu**:
    - "Explore this direction further" - Deep dive on specific hypothesis
    - "Compare with alternative" - Generate contrasting hypotheses
    - "Refine with new constraints" - Update parameters and re-run
    - "Validate with literature" - Additional literature review
    - "Generate experimental protocol" - Design experiments to test
- **Iteration History**: Track of follow-up interactions and their results
- **Branching Visualization**: Tree view of exploration paths

---

### 2.11 Sharing/Export Actions

**Purpose**: Distribute results and collaborate with others

**Components**:

- **Share Modal**:
    - Generate shareable link
    - Set permissions (view, comment, edit)
    - Email invitation
    - Export to Google Docs, Notion, Confluence
- **Export Options**:
    - PDF report
    - Word document
    - LaTeX for academic papers
    - JSON/CSV for data export
    - Markdown for documentation
- **Citation Export**: BibTeX, RIS, EndNote formats
- **Print View**: Optimized layout for printing

---

### 2.12 Settings

**Purpose**: Configure user preferences and system behavior

**Components**:

- **Profile Settings**: Name, affiliation, research interests
- **Notification Preferences**: Email, in-app, push notifications
- **Integration Settings**: Connected databases and tools
- **API Access**: API keys for programmatic access
- **Privacy Settings**: Data retention, sharing preferences
- **Appearance**: Theme, density, font size
- **Advanced Settings**: Agent behavior customization (for power users)

---

### 2.13 Project/History Management

**Purpose**: Organize and access past research runs

**Components**:

- **Project List**: All research runs with metadata
    - Date created
    - Status (completed, in-progress, draft)
    - Tags/categories
    - Search and filter
- **Folder Structure**: Organize runs into projects
- **Archive**: Old runs with reduced functionality
- **Duplication**: Clone existing runs for new iterations
- **Deletion**: Remove runs with confirmation

---

## 3. Navigation Model

### 3.1 Global Navigation Structure

#### Top Navigation Bar

- **Left**: Logo, Home button, New Research Goal (primary CTA)
- **Center**: Global search bar (search across all content)
- **Right**:
    - Notifications bell (with badge for active runs)
    - Help dropdown
    - User profile menu

#### Sidebar Navigation (Collapsible)

**Primary Sections**:

- **Dashboard**: Home hub
- **Research Workspace**:
    - New Research Goal
    - Active Runs
    - Recent Projects
- **Knowledge Base**:
    - My Knowledge Bases
    - Browse All
    - Saved Papers
- **History**:
    - Past Runs
    - Drafts
    - Archived
- **Collaboration**:
    - Shared with Me
    - Team Projects
- **Settings**

**Sidebar Behavior**:

- Collapsible to icons-only mode
- Persistent state across sessions
- Contextual highlighting based on current page
- Support for keyboard navigation (1-9 shortcuts)

### 3.2 Breadcrumb Navigation

- **Pattern**: Home > Research Workspace > [Project Name] > [Run Name] > [View Name]
- **Implementation**:
    - Truncate middle sections for long paths
    - Clickable for navigation up hierarchy
    - Current page non-clickable (bold)
- **Special Cases**:
    - Research runs: Show run status icon
    - Knowledge base: Show knowledge graph icon

### 3.3 Tab Navigation (Within Views)

- **Research Run View**:
    - Overview | Ideas | Knowledge Base | Tournament | Settings
- **Knowledge Base View**:
    - Graph | List | Search | Documents
- **Idea Detail View**:
    - Hypothesis | Evidence | Evolution | Discussion

### 3.4 Contextual Action Buttons

- **Floating Action Button (FAB)**: Primary action for current context
    - Home: New Research Goal
    - Run View: Add Feedback
    - Knowledge Base: Add Paper
- **Toolbar Actions**: Context-specific actions in header
- **Right-Click Context Menus**:
    - On ideas: Compare, Export, Follow-up
    - On papers: Cite, Save, View Full-text

### 3.5 Drawer Patterns

- **Right Drawer**:
    - Agent activity details
    - Citation details
    - User feedback input
- **Left Drawer**:
    - Filter panel for search results
    - Outline for long reports

---

## 4. Interaction Model

### 4.1 Research Goal Creation Workflow

**Step 1: Initiation**

- **Trigger**: User clicks "New Research Goal" button
- **State Change**:
    - Modal opens with goal input form
    - Background dims (overlay)
    - Focus on text input field
- **Input Methods**:
    - Type in text area
    - Voice input (microphone button)
    - Upload document (drag-drop or file picker)
    - Select from template

**Step 2: Clarification Interview**

- **Transition**: After initial input, modal expands to full-screen chat interface
- **Agent Behavior**:
    - AI assistant asks structured questions
    - Progress indicator shows completion status
    - Suggestion chips appear for quick responses
- **User Actions**:
    - Respond to questions
    - Skip optional questions
    - Upload supporting documents
    - Request clarification on questions
- **State Updates**:
    - Real-time update of research plan summary
    - Visual indication of information gathered

**Step 3: Review and Confirm**

- **Transition**: When sufficient information gathered, show review panel
- **Interface**: Split view with chat history and structured plan
- **User Actions**:
    - Edit sections directly
    - Request changes via chat
    - Approve and proceed
    - Save as draft
- **Validation**: Minimum required fields must be complete

**Step 4: Transition to Run Configuration**

- **Animation**: Smooth transition from interview to configuration
- **State**: Research plan pre-populated in configuration form

---

### 4.2 Run Configuration Workflow

**Step 1: Run Type Selection**

- **UI**: Card selection with comparison table
- **Interaction**:
    - Click card to select
    - Hover for detailed comparison
    - Default selection based on research goal complexity
- **State Change**: Selected card highlighted, others dimmed

**Step 2: Agent Configuration**

- **UI**: Toggle switches and sliders
- **Interaction**:
    - Toggle agents on/off
    - Adjust iteration counts
    - Set resource allocation
- **Validation**: At least Generation and Meta-review agents required

**Step 3: Knowledge Base Setup**

- **UI**: Multi-select with search
- **Interaction**:
    - Select integrated databases
    - Upload files (drag-drop zone)
    - Set citation preferences
- **Feedback**: File upload progress, database connection status

**Step 4: Final Review**

- **UI**: Summary panel with confirmation
- **Interaction**:
    - Review all settings
    - Edit any section
    - Confirm and start run
- **State Change**:
    - Configuration saved
    - Transition to monitoring view
    - Run initialization begins

---

### 4.3 Active Run Monitoring Workflow

**Step 1: Initialization**

- **UI**: Loading screen with agent initialization animation
- **State**:
    - Setup progress bar
    - Agent status indicators (pending → initializing → ready)
    - Estimated start time

**Step 2: Execution**

- **UI**: Full monitoring dashboard
- **Real-time Updates**:
    - Progress bar advances
    - Agent activity indicators pulse when active
    - Log stream scrolls with latest actions
    - Knowledge base counter increments
- **User Interactions**:
    - Can click on agent status for details
    - Can expand/collapse log sections
    - Can pause run (button in header)
    - Can add feedback via side panel

**Step 3: Mid-run Intervention**

- **Trigger**: User clicks "Add Feedback" or "Pause"
- **State Change**:
    - Run pauses (if applicable)
    - Feedback modal opens
    - Current agent activities suspended
- **Interaction**:
    - User provides feedback
    - System acknowledges and incorporates
    - Run resumes or continues with new parameters

**Step 4: Completion**

- **Transition**: Progress reaches 100%
- **Animation**: Completion celebration, then transition to results
- **State Change**:
    - Run status changes to "Completed"
    - Results populated in all views
    - Notification sent to user

---

### 4.4 Results Exploration Workflow

**Step 1: Initial Review**

- **UI**: Overview dashboard with summary
- **Interaction**:
    - Scroll through ranked hypotheses
    - Click on hypothesis for details
    - Filter and sort results
    - Export summary

**Step 2: Deep Dive**

- **Transition**: Click on specific hypothesis
- **UI**: Detailed view with multiple tabs
- **Interaction**:
    - Review reasoning chain
    - Examine evidence
    - View evolution history
    - Add user notes
    - Compare with other hypotheses

**Step 3: Knowledge Base Exploration**

- **Transition**: Navigate to knowledge base from hypothesis
- **UI**: Graph and list views
- **Interaction**:
    - Explore citation network
    - Search for related papers
    - Export relevant sections
    - Add to saved papers

**Step 4: Follow-up Actions**

- **UI**: Follow-up agent interface
- **Interaction**:
    - Chat with follow-up agent
    - Request additional analysis
    - Start new run based on findings
    - Share results

---

### 4.5 Sharing and Export Workflow

**Step 1: Initiation**

- **Trigger**: User clicks share or export button
- **UI**: Modal with options
- **State**: Content prepared for sharing

**Step 2: Configure Sharing**

- **Interaction**:
    - Select recipients
    - Set permissions
    - Add message
    - Generate link or send email

**Step 3: Export Format Selection**

- **Interaction**:
    - Select format (PDF, Word, etc.)
    - Configure export options
    - Preview export
    - Confirm download

**Step 4: Completion**

- **State**:
    - Sharing link generated or email sent
    - Download starts
    - Modal closes or shows confirmation

---

## 5. Component Specifications

### 5.1 Chat/Conversation Interface

- **Message Bubbles**: User (right, blue) vs. Agent (left, gray)
- **Rich Content**: Support for tables, code blocks, citations in messages
- **Input Area**:
    - Text input with formatting toolbar
    - Voice input button
    - File attachment button
    - Send button (or Enter key)
- **Typing Indicator**: Animated dots when agent is processing
- **Message History**: Scrollable with load more for long conversations

### 5.2 Research Run Card

- **Header**: Run name, status badge, date created
- **Progress Section**:
    - Progress bar with percentage
    - Time elapsed/estimated
    - Agent activity icons
- **Actions**:
    - Open/View (primary)
    - Pause/Resume (contextual)
    - Delete (with confirmation)
- **Metadata**: Tags, number of hypotheses, knowledge base size

### 5.3 Hypothesis Card

- **Header**: Rank number, ELO score, confidence badge
- **Content**:
    - Hypothesis statement (truncated with expand)
    - Key supporting evidence
    - Novelty assessment
- **Actions**:
    - View Details
    - Compare
    - Export
    - Add to Favorites

### 5.4 Knowledge Base Graph

- **Visualization**: Force-directed graph with nodes and edges
- **Node Types**:
    - Papers (circles, sized by relevance)
    - Concepts (diamonds)
    - Hypotheses (hexagons)
- **Interactions**:
    - Zoom and pan
    - Click to select
    - Hover for preview
    - Filter by type
- **Legend**: Explanation of symbols and colors

### 5.5 Agent Activity Indicator

- **Visual**: Animated pulse or icon for active agents
- **Tooltip**: Current task description on hover
- **Panel**: Expandable view with detailed activity log
- **Status States**:
    - Inactive (gray)
    - Initializing (yellow pulse)
    - Active (green pulse)
    - Completed (checkmark)
    - Error (red with message)

### 5.6 Tournament Visualization

- **View Modes**:
    - Bracket view (tournament style)
    - ELO chart (rating over time)
    - Head-to-head comparison
- **Interactions**:
    - Click match to see debate transcript
    - Hover for score details
    - Filter by round or agent

---

## 6. State Management & Transitions

### 6.1 Global States

- **Authentication**: Unauthenticated → Authenticating → Authenticated
- **Connection**: Online → Offline → Reconnecting
- **System Status**: Operational → Degraded → Maintenance

### 6.2 Research Run States

```
Draft → Configuring → Queued → Initializing → Running → Paused → Completed/Failed
```

### 6.3 View States

- **Loading**: Skeleton screens with shimmer effect
- **Empty**: Empty state with CTA
- **Error**: Error message with retry option
- **Success**: Content displayed

---

## 7. Responsive Design Considerations

### 7.1 Desktop (Primary)

- **Layout**: Sidebar + Main Content + Right Panel (optional)
- **Navigation**: Full sidebar with text labels
- **Content**: Multi-column layouts, side-by-side comparisons

### 7.2 Tablet

- **Layout**: Collapsible sidebar, single main content area
- **Navigation**: Icon-only sidebar, expandable on hover
- **Content**: Single column, tabs for secondary content

### 7.3 Mobile (Limited Support)

- **Layout**: Bottom navigation, single column
- **Navigation**: Bottom bar with key actions
- **Content**: Stacked cards, simplified views
- **Note**: Complex research workflows may require desktop

---

## 8. Accessibility Requirements

- **Keyboard Navigation**: Full support for Tab, Enter, Escape, Arrow keys
- **Screen Reader**: ARIA labels, semantic HTML, focus management
- **Color Contrast**: WCAG AA compliance minimum
- **Motion**: Respect prefers-reduced-motion
- **Zoom**: Support up to 200% without horizontal scroll

---

## 9. Performance Guidelines

- **Initial Load**: Under 3 seconds
- **Time to Interactive**: Under 5 seconds
- **Run Progress Updates**: Real-time (WebSocket or SSE)
- **Search Response**: Under 500ms
- **Large Report Rendering**: Progressive loading with virtualization

---

## 10. Appendices

### A. User Flow Diagrams

**Main Flow: New Research Goal → Results**

```
[Home] → [New Research Goal] → [Interview] → [Configuration] → [Monitoring] → [Results] → [Export/Share]
```

**Secondary Flow: Continue Previous Work**

```
[Home] → [Recent Projects] → [Select Run] → [Results/Monitoring] → [Follow-up Agent]
```

### B. State Machine Definitions

**Research Run State Machine:**

- States: Draft, Configuring, Queued, Initializing, Running, Paused, Completed, Failed
- Transitions:
    - Draft → Configuring: User starts configuration
    - Configuring → Queued: User confirms and starts
    - Queued → Initializing: Resources allocated
    - Initializing → Running: Agents started
    - Running → Paused: User pauses or intervention needed
    - Paused → Running: User resumes
    - Running → Completed: All tasks finished
    - Running → Failed: Error encountered

### C. Data Models

**Research Goal:**

```
{
  id: string,
  title: string,
  description: string,
  focusAreas: string[],
  constraints: string[],
  preferences: object,
  createdAt: timestamp,
  updatedAt: timestamp,
  status: enum
}
```

**Research Run:**

```
{
  id: string,
  goalId: string,
  configuration: object,
  status: enum,
  progress: number,
  agents: AgentStatus[],
  startTime: timestamp,
  endTime: timestamp,
  results: ResultsObject,
  knowledgeBase: KnowledgeBaseRef
}
```

---

**Document Version**: 1.0  
**Last Updated**: 2026-06-07  
**Source**: Based on Google DeepMind AI Co-Scientist research papers, Nature publication, and Google Labs Hypothesis Generation tool analysis.

---

The full detailed document with visual references and expanded specifications is available at: AI Co-Scientist Product Blueprint[4](https://www.genspark.ai/api/files/s/hDWHvarK)

This blueprint provides a complete specification for implementing the AI Co-Scientist clone, covering all screens, navigation patterns, interaction flows, and component specifications needed for design and development teams.

---

## Appendix: Supplementary Video Resources

<div class="-md-ext-youtube-widget"> { "title": "Generating novel scientific hypotheses with Co-Scientist", "link": "https://www.youtube.com/watch?v=aSY_vFFmkW0", "channel": { "name": ""}, "published_date": "3 weeks ago", "length": "6:27" }</div>

<div class="-md-ext-youtube-widget"> { "title": "Google's AI Co-Scientist Explained", "link": "https://www.youtube.com/watch?v=x-ZqPELgYQA", "channel": { "name": ""}, "published_date": "Apr 24, 2025", "length": "24:14" }</div>

<div class="-md-ext-youtube-widget"> { "title": "Real-time Experiments with an AI Co-Scientist - Stefania ...", "link": "https://www.youtube.com/watch?v=wNH3q9pqn0U", "channel": { "name": ""}, "published_date": "Jul 28, 2025", "length": "18:42" }</div>

Generated with sparks and insights from 4 sources

```
 I've created a comprehensive product blueprint document. Let me provide you with the key findings and structure here, with the full detailed document available via the link.
```

---

#   

Based on my comprehensive research of Google DeepMind's AI Co-Scientist[1](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/) system, Nature publication[2](https://www.nature.com/articles/s41586-026-10644-y), and Google Labs Hypothesis Generation[3](https://labs.google/science/) tool, here is the complete product blueprint:

---

## 1. Information Architecture

### System Overview

The AI Co-Scientist clone follows a **hub-and-spoke architecture** with a central workspace hub connecting to specialized functional modules. The system implements a multi-agent workflow (Generate → Debate → Evolve) accessible through a conversational interface.

### Content Hierarchy

```
Platform Hub (Home)
├── Onboarding & Welcome
├── Research Workspace
│   ├── Goal Creation Flow
│   ├── Interview/Refinement
│   ├── Run Configuration
│   ├── Active Run Monitoring
│   └── Results & Reports
│       ├── Ideas Report
│       ├── Knowledge Base
│       ├── Summary Report
│       └── Detailed Proposals
├── Follow-up Agent Interactions
├── Project Management
│   ├── History/Archive
│   ├── Saved Runs
│   └── Drafts
├── Knowledge Base
├── Settings & Preferences
└── Help & Documentation
```

### Data Flow Architecture

- **Input Layer**: Natural language research goals, user feedback, uploaded documents
    
- **Processing Layer**: Multi-agent system (Generation, Reflection, Ranking, Evolution, Proximity, Meta-review, Supervisor agents)
    
- **Output Layer**: Structured reports, hypotheses, knowledge bases, ranked ideas
    
- **Storage Layer**: Context memory, run history, user preferences, knowledge graph
    

---

## 2. Screen Inventory

### 2.1 Home/Hub Page

**Purpose**: Central dashboard and entry point for all research activities

**Components**:

- **Header**: Logo, search bar, notifications, user profile
    
- **Quick Start Section**: "New Research Goal" prominent CTA button
    
- **Active Runs Panel**: Cards showing ongoing research runs with progress indicators
    
- **Recent Projects**: List of recent research goals with quick access
    
- **Templates Gallery**: Pre-built research templates (Drug Discovery, Target Identification, Mechanism Analysis, etc.)
    
- **Activity Feed**: Recent system updates, completed runs, shared projects
    
- **Quick Actions**: Import from literature, Continue previous run, Explore knowledge base
    

**State Variations**:

- **First-time user**: Welcome banner with onboarding CTA
    
- **Returning user**: Personalized greeting with recent activity
    
- **Active runs**: Real-time progress indicators in sidebar
    

---

### 2.2 Onboarding/Welcome Experience

**Purpose**: Introduce new users to the platform capabilities and collect initial preferences

**Components**:

- **Welcome Screen**: Value proposition with animated demo of the workflow
    
- **Capability Tour**: Interactive walkthrough of key features:
    
    - Multi-agent hypothesis generation
        
    - Tournament-style evaluation
        
    - Knowledge base integration
        
    - Follow-up agent interactions
        
- **Research Domain Selection**: Pre-configure for user's field (Life Sciences, Materials Science, Physics, etc.)
    
- **Integration Setup**: Connect external databases (PubMed, ChEMBL, UniProt, etc.)
    
- **Notification Preferences**: Email alerts for run completion, weekly digests
    

**Interaction Flow**:

1. Welcome modal with video/demo
    
2. Interactive feature tour (4-5 steps)
    
3. Domain and preference selection
    
4. Optional integration configuration
    
5. First research goal prompt
    

---

### 2.3 Research Goal Creation Flow

**Purpose**: Capture user's research challenge and refine through conversational interview

**Components**:

- **Goal Input Modal**: Large text area for research challenge description
    
- **Conversation Interface**: Chat-style interface with AI assistant
    
- **Progress Indicators**: Steps showing (Challenge → Focus Area → Preferences → Review)
    
- **Template Selector**: Pre-built prompts for common research types
    
- **Voice Input**: Optional speech-to-text for goal input
    

**Interaction Flow**:

1. **Initial Input**: User enters research challenge in natural language
    
2. **Clarification Questions**: AI asks follow-up questions to refine:
    
    - Specific research question
        
    - Hypotheses to explore/test
        
    - Focus areas and constraints
        
    - Preferences (novelty vs. feasibility, breadth vs. depth)
        
3. **Summarization**: AI presents structured research plan
    
4. **User Review**: User can edit or approve the plan
    
5. **Transition to Run Configuration**
    

**UI States**:

- **Input state**: Empty text area with placeholder examples
    
- **Processing state**: Typing indicator while AI analyzes input
    
- **Clarification state**: Chat interface with Q&A
    
- **Review state**: Structured plan with edit capabilities
    

---

### 2.4 Interview/Refinement Flow

**Purpose**: Structured conversational interface to build comprehensive research specification

**Components**:

- **Chat Interface**: Full-screen or side-panel chat with agent
    
- **Context Panel**: Shows current understanding of research goal
    
- **Structured Form**: Optional tabular view of specifications
    
- **Suggestion Chips**: Pre-defined options for quick responses
    
- **File Upload**: Support for uploading relevant papers, datasets
    

**Key Interview Topics**:

- Research Challenge: Core problem statement
    
- Focus Area: Specific domains or mechanisms to explore
    
- Hypotheses: Specific hypotheses to test or explore
    
- Constraints: Ethical, technical, resource limitations
    
- Preferences: Output format preferences (NIH format, grant proposal, etc.)
    

**State Management**:

- Real-time updates to research plan as user provides input
    
- Visual indication of completion status for each section
    
- Ability to save as draft and return later
    

---

### 2.5 Run Configuration

**Purpose**: Configure execution parameters before starting the multi-agent research run

**Components**:

- **Run Type Selection**:
    
    - **Standard Run**: ~20-30 hypotheses, 2-4 hours, comprehensive analysis
        
    - **Advanced Run**: ~50+ hypotheses, 6-8 hours, deep exploration with additional agents
        
- **Agent Configuration**:
    
    - Toggle specific agents on/off
        
    - Set agent weights/resource allocation
        
    - Configure evolution iterations
        
- **Knowledge Base Settings**:
    
    - Select integrated databases
        
    - Upload additional literature
        
    - Set recency preferences for citations
        
- **Output Preferences**:
    
    - Report format (NIH Specific Aims, standard research proposal, etc.)
        
    - Detail level (Executive summary vs. comprehensive)
        
    - Citation style
        
- **Notification Settings**: Email on completion, progress updates
    

**Confirmation Panel**:

- Summary of configuration
    
- Estimated time and cost
    
- Final confirmation button
    

---

### 2.6 Active Run Monitoring

**Purpose**: Real-time visibility into multi-agent research execution

**Components**:

- **Progress Dashboard**:
    
    - Overall progress bar with percentage
        
    - Estimated time remaining
        
    - Agent activity status indicators
        
- **Agent Activity Panel**: Live view of which agents are active:
    
    - Generation Agent: Creating hypotheses
        
    - Reflection Agent: Reviewing and critiquing
        
    - Ranking Agent: Running tournaments
        
    - Evolution Agent: Refining top hypotheses
        
    - Meta-review Agent: Synthesizing findings
        
- **Live Log Stream**: Real-time updates of agent actions
    
- **Knowledge Base Growth**: Visual showing accumulating references
    
- **Tournament Visualization**: Interactive view of hypothesis competition
    
    - ELO rating changes
        
    - Head-to-head match results
        
    - Debate transcripts
        
- **Intervention Points**: Ability to:
    
    - Add user feedback mid-run
        
    - Pause/resume run
        
    - Provide additional context
        
    - Early termination with partial results
        

**UI States**:

- **Initializing**: Agent setup and task queue creation
    
- **Running**: Live progress with animated indicators
    
- **Paused**: Awaiting user input or resumption
    
- **Completing**: Final synthesis and report generation
    
- **Completed**: Results ready for review
    

---

### 2.7 Generated Report Pages

#### 2.7.1 Ideas Report

**Purpose**: Present ranked hypotheses with supporting evidence

**Components**:

- **Executive Summary**: Top 3-5 hypotheses with key points
    
- **Ranked Hypothesis List**:
    
    - ELO score and ranking
        
    - Hypothesis statement
        
    - Supporting evidence summary
        
    - Confidence score
        
    - Novelty assessment
        
- **Tournament Results**: Visualization of the competition process
    
- **Debate Transcripts**: Records of agent discussions
    
- **Comparison Tool**: Side-by-side comparison of multiple hypotheses
    

#### 2.7.2 Knowledge Base

**Purpose**: Comprehensive literature review with verified references

**Components**:

- **Search Interface**: Full-text search across gathered literature
    
- **Reference List**: All papers and sources used
    
    - Title, authors, year
        
    - Relevance score
        
    - Citation context
        
    - Full-text access links
        
- **Topic Clusters**: Visual map of research themes
    
- **Citation Network**: Graph showing paper relationships
    
- **Evidence Table**: Structured extraction of key findings
    

#### 2.7.3 Summary Report

**Purpose**: High-level overview of research findings

**Components**:

- **Research Goal Recap**: Original challenge and specifications
    
- **Key Findings**: Synthesized insights
    
- **Recommended Next Steps**: Actionable research directions
    
- **Limitations**: Critical flaws and non-viable directions identified
    
- **Export Options**: PDF, Word, Markdown, LaTeX
    

#### 2.7.4 Detailed Proposal

**Purpose**: Full research proposal for grant applications or research planning

**Components**:

- **Structured Sections**:
    
    - Specific Aims (if NIH format)
        
    - Background and Significance
        
    - Research Design and Methods
        
    - Expected Outcomes
        
    - Timeline and Milestones
        
- **Citation Management**: Properly formatted references
    
- **Budget Justification**: Optional section for grant applications
    

---

### 2.8 Idea Detail View

**Purpose**: Deep dive into individual hypothesis with full reasoning

**Components**:

- **Hypothesis Statement**: Clear, testable formulation
    
- **Reasoning Chain**: Step-by-step logic supporting the hypothesis
    
- **Evidence Base**: Specific papers and data points
    
- **Novelty Assessment**: Comparison to existing research
    
- **Testability Analysis**: Experimental design suggestions
    
- **Agent Evolution History**: How the hypothesis was refined through iterations
    
- **User Notes**: Space for researcher annotations
    
- **Follow-up Actions**: Links to related ideas or knowledge base entries
    

---

### 2.9 Knowledge Base Views

**Purpose**: Explore and interact with the accumulated research knowledge

**Components**:

- **Graph Visualization**: Interactive network of papers, concepts, and hypotheses
    
- **Semantic Search**: Natural language queries across the knowledge base
    
- **Document Viewer**: Full-text access with annotation tools
    
- **Citation Context**: See how papers were cited in generated hypotheses
    
- **Export Tools**: Download subsets of the knowledge base
    
- **Follow-up Queries**: Ask questions about the accumulated knowledge
    

---

### 2.10 Follow-up Agent Interaction

**Purpose**: Continue refinement and exploration based on initial results

**Components**:

- **Chat Interface**: Natural language conversation with follow-up agent
    
- **Context Panel**: Reference to original run and current findings
    
- **Action Menu**:
    
    - "Explore this direction further" - Deep dive on specific hypothesis
        
    - "Compare with alternative" - Generate contrasting hypotheses
        
    - "Refine with new constraints" - Update parameters and re-run
        
    - "Validate with literature" - Additional literature review
        
    - "Generate experimental protocol" - Design experiments to test
        
- **Iteration History**: Track of follow-up interactions and their results
    
- **Branching Visualization**: Tree view of exploration paths
    

---

### 2.11 Sharing/Export Actions

**Purpose**: Distribute results and collaborate with others

**Components**:

- **Share Modal**:
    
    - Generate shareable link
        
    - Set permissions (view, comment, edit)
        
    - Email invitation
        
    - Export to Google Docs, Notion, Confluence
        
- **Export Options**:
    
    - PDF report
        
    - Word document
        
    - LaTeX for academic papers
        
    - JSON/CSV for data export
        
    - Markdown for documentation
        
- **Citation Export**: BibTeX, RIS, EndNote formats
    
- **Print View**: Optimized layout for printing
    

---

### 2.12 Settings

**Purpose**: Configure user preferences and system behavior

**Components**:

- **Profile Settings**: Name, affiliation, research interests
    
- **Notification Preferences**: Email, in-app, push notifications
    
- **Integration Settings**: Connected databases and tools
    
- **API Access**: API keys for programmatic access
    
- **Privacy Settings**: Data retention, sharing preferences
    
- **Appearance**: Theme, density, font size
    
- **Advanced Settings**: Agent behavior customization (for power users)
    

---

### 2.13 Project/History Management

**Purpose**: Organize and access past research runs

**Components**:

- **Project List**: All research runs with metadata
    
    - Date created
        
    - Status (completed, in-progress, draft)
        
    - Tags/categories
        
    - Search and filter
        
- **Folder Structure**: Organize runs into projects
    
- **Archive**: Old runs with reduced functionality
    
- **Duplication**: Clone existing runs for new iterations
    
- **Deletion**: Remove runs with confirmation
    

---

## 3. Navigation Model

### 3.1 Global Navigation Structure

#### Top Navigation Bar

- **Left**: Logo, Home button, New Research Goal (primary CTA)
    
- **Center**: Global search bar (search across all content)
    
- **Right**:
    
    - Notifications bell (with badge for active runs)
        
    - Help dropdown
        
    - User profile menu
        

#### Sidebar Navigation (Collapsible)

**Primary Sections**:

- **Dashboard**: Home hub
    
- **Research Workspace**:
    
    - New Research Goal
        
    - Active Runs
        
    - Recent Projects
        
- **Knowledge Base**:
    
    - My Knowledge Bases
        
    - Browse All
        
    - Saved Papers
        
- **History**:
    
    - Past Runs
        
    - Drafts
        
    - Archived
        
- **Collaboration**:
    
    - Shared with Me
        
    - Team Projects
        
- **Settings**
    

**Sidebar Behavior**:

- Collapsible to icons-only mode
    
- Persistent state across sessions
    
- Contextual highlighting based on current page
    
- Support for keyboard navigation (1-9 shortcuts)
    

### 3.2 Breadcrumb Navigation

- **Pattern**: Home > Research Workspace > [Project Name] > [Run Name] > [View Name]
    
- **Implementation**:
    
    - Truncate middle sections for long paths
        
    - Clickable for navigation up hierarchy
        
    - Current page non-clickable (bold)
        
- **Special Cases**:
    
    - Research runs: Show run status icon
        
    - Knowledge base: Show knowledge graph icon
        

### 3.3 Tab Navigation (Within Views)

- **Research Run View**:
    
    - Overview | Ideas | Knowledge Base | Tournament | Settings
        
- **Knowledge Base View**:
    
    - Graph | List | Search | Documents
        
- **Idea Detail View**:
    
    - Hypothesis | Evidence | Evolution | Discussion
        

### 3.4 Contextual Action Buttons

- **Floating Action Button (FAB)**: Primary action for current context
    
    - Home: New Research Goal
        
    - Run View: Add Feedback
        
    - Knowledge Base: Add Paper
        
- **Toolbar Actions**: Context-specific actions in header
    
- **Right-Click Context Menus**:
    
    - On ideas: Compare, Export, Follow-up
        
    - On papers: Cite, Save, View Full-text
        

### 3.5 Drawer Patterns

- **Right Drawer**:
    
    - Agent activity details
        
    - Citation details
        
    - User feedback input
        
- **Left Drawer**:
    
    - Filter panel for search results
        
    - Outline for long reports
        

---

## 4. Interaction Model

### 4.1 Research Goal Creation Workflow

**Step 1: Initiation**

- **Trigger**: User clicks "New Research Goal" button
    
- **State Change**:
    
    - Modal opens with goal input form
        
    - Background dims (overlay)
        
    - Focus on text input field
        
- **Input Methods**:
    
    - Type in text area
        
    - Voice input (microphone button)
        
    - Upload document (drag-drop or file picker)
        
    - Select from template
        

**Step 2: Clarification Interview**

- **Transition**: After initial input, modal expands to full-screen chat interface
    
- **Agent Behavior**:
    
    - AI assistant asks structured questions
        
    - Progress indicator shows completion status
        
    - Suggestion chips appear for quick responses
        
- **User Actions**:
    
    - Respond to questions
        
    - Skip optional questions
        
    - Upload supporting documents
        
    - Request clarification on questions
        
- **State Updates**:
    
    - Real-time update of research plan summary
        
    - Visual indication of information gathered
        

**Step 3: Review and Confirm**

- **Transition**: When sufficient information gathered, show review panel
    
- **Interface**: Split view with chat history and structured plan
    
- **User Actions**:
    
    - Edit sections directly
        
    - Request changes via chat
        
    - Approve and proceed
        
    - Save as draft
        
- **Validation**: Minimum required fields must be complete
    

**Step 4: Transition to Run Configuration**

- **Animation**: Smooth transition from interview to configuration
    
- **State**: Research plan pre-populated in configuration form
    

---

### 4.2 Run Configuration Workflow

**Step 1: Run Type Selection**

- **UI**: Card selection with comparison table
    
- **Interaction**:
    
    - Click card to select
        
    - Hover for detailed comparison
        
    - Default selection based on research goal complexity
        
- **State Change**: Selected card highlighted, others dimmed
    

**Step 2: Agent Configuration**

- **UI**: Toggle switches and sliders
    
- **Interaction**:
    
    - Toggle agents on/off
        
    - Adjust iteration counts
        
    - Set resource allocation
        
- **Validation**: At least Generation and Meta-review agents required
    

**Step 3: Knowledge Base Setup**

- **UI**: Multi-select with search
    
- **Interaction**:
    
    - Select integrated databases
        
    - Upload files (drag-drop zone)
        
    - Set citation preferences
        
- **Feedback**: File upload progress, database connection status
    

**Step 4: Final Review**

- **UI**: Summary panel with confirmation
    
- **Interaction**:
    
    - Review all settings
        
    - Edit any section
        
    - Confirm and start run
        
- **State Change**:
    
    - Configuration saved
        
    - Transition to monitoring view
        
    - Run initialization begins
        

---

### 4.3 Active Run Monitoring Workflow

**Step 1: Initialization**

- **UI**: Loading screen with agent initialization animation
    
- **State**:
    
    - Setup progress bar
        
    - Agent status indicators (pending → initializing → ready)
        
    - Estimated start time
        

**Step 2: Execution**

- **UI**: Full monitoring dashboard
    
- **Real-time Updates**:
    
    - Progress bar advances
        
    - Agent activity indicators pulse when active
        
    - Log stream scrolls with latest actions
        
    - Knowledge base counter increments
        
- **User Interactions**:
    
    - Can click on agent status for details
        
    - Can expand/collapse log sections
        
    - Can pause run (button in header)
        
    - Can add feedback via side panel
        

**Step 3: Mid-run Intervention**

- **Trigger**: User clicks "Add Feedback" or "Pause"
    
- **State Change**:
    
    - Run pauses (if applicable)
        
    - Feedback modal opens
        
    - Current agent activities suspended
        
- **Interaction**:
    
    - User provides feedback
        
    - System acknowledges and incorporates
        
    - Run resumes or continues with new parameters
        

**Step 4: Completion**

- **Transition**: Progress reaches 100%
    
- **Animation**: Completion celebration, then transition to results
    
- **State Change**:
    
    - Run status changes to "Completed"
        
    - Results populated in all views
        
    - Notification sent to user
        

---

### 4.4 Results Exploration Workflow

**Step 1: Initial Review**

- **UI**: Overview dashboard with summary
    
- **Interaction**:
    
    - Scroll through ranked hypotheses
        
    - Click on hypothesis for details
        
    - Filter and sort results
        
    - Export summary
        

**Step 2: Deep Dive**

- **Transition**: Click on specific hypothesis
    
- **UI**: Detailed view with multiple tabs
    
- **Interaction**:
    
    - Review reasoning chain
        
    - Examine evidence
        
    - View evolution history
        
    - Add user notes
        
    - Compare with other hypotheses
        

**Step 3: Knowledge Base Exploration**

- **Transition**: Navigate to knowledge base from hypothesis
    
- **UI**: Graph and list views
    
- **Interaction**:
    
    - Explore citation network
        
    - Search for related papers
        
    - Export relevant sections
        
    - Add to saved papers
        

**Step 4: Follow-up Actions**

- **UI**: Follow-up agent interface
    
- **Interaction**:
    
    - Chat with follow-up agent
        
    - Request additional analysis
        
    - Start new run based on findings
        
    - Share results
        

---

### 4.5 Sharing and Export Workflow

**Step 1: Initiation**

- **Trigger**: User clicks share or export button
    
- **UI**: Modal with options
    
- **State**: Content prepared for sharing
    

**Step 2: Configure Sharing**

- **Interaction**:
    
    - Select recipients
        
    - Set permissions
        
    - Add message
        
    - Generate link or send email
        

**Step 3: Export Format Selection**

- **Interaction**:
    
    - Select format (PDF, Word, etc.)
        
    - Configure export options
        
    - Preview export
        
    - Confirm download
        

**Step 4: Completion**

- **State**:
    
    - Sharing link generated or email sent
        
    - Download starts
        
    - Modal closes or shows confirmation
        

---

## 5. Component Specifications

### 5.1 Chat/Conversation Interface

- **Message Bubbles**: User (right, blue) vs. Agent (left, gray)
    
- **Rich Content**: Support for tables, code blocks, citations in messages
    
- **Input Area**:
    
    - Text input with formatting toolbar
        
    - Voice input button
        
    - File attachment button
        
    - Send button (or Enter key)
        
- **Typing Indicator**: Animated dots when agent is processing
    
- **Message History**: Scrollable with load more for long conversations
    

### 5.2 Research Run Card

- **Header**: Run name, status badge, date created
    
- **Progress Section**:
    
    - Progress bar with percentage
        
    - Time elapsed/estimated
        
    - Agent activity icons
        
- **Actions**:
    
    - Open/View (primary)
        
    - Pause/Resume (contextual)
        
    - Delete (with confirmation)
        
- **Metadata**: Tags, number of hypotheses, knowledge base size
    

### 5.3 Hypothesis Card

- **Header**: Rank number, ELO score, confidence badge
    
- **Content**:
    
    - Hypothesis statement (truncated with expand)
        
    - Key supporting evidence
        
    - Novelty assessment
        
- **Actions**:
    
    - View Details
        
    - Compare
        
    - Export
        
    - Add to Favorites
        

### 5.4 Knowledge Base Graph

- **Visualization**: Force-directed graph with nodes and edges
    
- **Node Types**:
    
    - Papers (circles, sized by relevance)
        
    - Concepts (diamonds)
        
    - Hypotheses (hexagons)
        
- **Interactions**:
    
    - Zoom and pan
        
    - Click to select
        
    - Hover for preview
        
    - Filter by type
        
- **Legend**: Explanation of symbols and colors
    

### 5.5 Agent Activity Indicator

- **Visual**: Animated pulse or icon for active agents
    
- **Tooltip**: Current task description on hover
    
- **Panel**: Expandable view with detailed activity log
    
- **Status States**:
    
    - Inactive (gray)
        
    - Initializing (yellow pulse)
        
    - Active (green pulse)
        
    - Completed (checkmark)
        
    - Error (red with message)
        

### 5.6 Tournament Visualization

- **View Modes**:
    
    - Bracket view (tournament style)
        
    - ELO chart (rating over time)
        
    - Head-to-head comparison
        
- **Interactions**:
    
    - Click match to see debate transcript
        
    - Hover for score details
        
    - Filter by round or agent
        

---

## 6. State Management & Transitions

### 6.1 Global States

- **Authentication**: Unauthenticated → Authenticating → Authenticated
    
- **Connection**: Online → Offline → Reconnecting
    
- **System Status**: Operational → Degraded → Maintenance
    

### 6.2 Research Run States

```
Draft → Configuring → Queued → Initializing → Running → Paused → Completed/Failed
```

### 6.3 View States

- **Loading**: Skeleton screens with shimmer effect
    
- **Empty**: Empty state with CTA
    
- **Error**: Error message with retry option
    
- **Success**: Content displayed
    

---

## 7. Responsive Design Considerations

### 7.1 Desktop (Primary)

- **Layout**: Sidebar + Main Content + Right Panel (optional)
    
- **Navigation**: Full sidebar with text labels
    
- **Content**: Multi-column layouts, side-by-side comparisons
    

### 7.2 Tablet

- **Layout**: Collapsible sidebar, single main content area
    
- **Navigation**: Icon-only sidebar, expandable on hover
    
- **Content**: Single column, tabs for secondary content
    

### 7.3 Mobile (Limited Support)

- **Layout**: Bottom navigation, single column
    
- **Navigation**: Bottom bar with key actions
    
- **Content**: Stacked cards, simplified views
    
- **Note**: Complex research workflows may require desktop
    

---

## 8. Accessibility Requirements

- **Keyboard Navigation**: Full support for Tab, Enter, Escape, Arrow keys
    
- **Screen Reader**: ARIA labels, semantic HTML, focus management
    
- **Color Contrast**: WCAG AA compliance minimum
    
- **Motion**: Respect prefers-reduced-motion
    
- **Zoom**: Support up to 200% without horizontal scroll
    

---

## 9. Performance Guidelines

- **Initial Load**: Under 3 seconds
    
- **Time to Interactive**: Under 5 seconds
    
- **Run Progress Updates**: Real-time (WebSocket or SSE)
    
- **Search Response**: Under 500ms
    
- **Large Report Rendering**: Progressive loading with virtualization
    

---

## 10. Appendices

### A. User Flow Diagrams

**Main Flow: New Research Goal → Results**

```
[Home] → [New Research Goal] → [Interview] → [Configuration] → [Monitoring] → [Results] → [Export/Share]
```

**Secondary Flow: Continue Previous Work**

```
[Home] → [Recent Projects] → [Select Run] → [Results/Monitoring] → [Follow-up Agent]
```

### B. State Machine Definitions

**Research Run State Machine:**

- States: Draft, Configuring, Queued, Initializing, Running, Paused, Completed, Failed
    
- Transitions:
    
    - Draft → Configuring: User starts configuration
        
    - Configuring → Queued: User confirms and starts
        
    - Queued → Initializing: Resources allocated
        
    - Initializing → Running: Agents started
        
    - Running → Paused: User pauses or intervention needed
        
    - Paused → Running: User resumes
        
    - Running → Completed: All tasks finished
        
    - Running → Failed: Error encountered
        

### C. Data Models

**Research Goal:**

```
{
  id: string,
  title: string,
  description: string,
  focusAreas: string[],
  constraints: string[],
  preferences: object,
  createdAt: timestamp,
  updatedAt: timestamp,
  status: enum
}
```

**Research Run:**

```
{
  id: string,
  goalId: string,
  configuration: object,
  status: enum,
  progress: number,
  agents: AgentStatus[],
  startTime: timestamp,
  endTime: timestamp,
  results: ResultsObject,
  knowledgeBase: KnowledgeBaseRef
}
```
