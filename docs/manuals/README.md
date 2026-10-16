# SikaFriend Project and Role Manuals

These manuals describe the system as configured in the standalone SikaFriend Micro-Credit ERP.

## Client handover edition

Share **[SikaFriend Client User Manual (PDF)](SikaFriend_Client_User_Manual.pdf)** with the client. This edition contains **121 pages and 82 screenshots**, with 26 operating chapters and two practical appendices. It covers management, operations, officers, finance and borrower self-service using menu-based instructions and the project brand colors, including authenticator enrollment and recovery.

The client edition omits implementation references, routes, schema tables, installation/deployment commands, credential exposure history and project-specific repair/loan-review details. It keeps the operational approval/reversal rules, payment verification guidance, financial examples and privacy instructions users need.

The [client HTML edition](SikaFriend_Client_User_Manual.html) contains the same text and embedded pictures. Its editable source is [client_manual_content.html](client_manual_content.html). Rebuild from the project root with:

```bash
.venv/bin/python docs/manuals/build_client_manual.py
```

The client builder uses approved sample screenshots and report labels without initializing the application or reading a database. It validates internal links and rejects known internal engineering topics. [client_manual_build.json](client_manual_build.json) records the page count, chapter starts and checksum. Share the client PDF/HTML rather than the internal source/reference files below.

## Internal project reference

The internal handbook is **[SikaFriend Complete Project Manual (PDF)](SikaFriend_Complete_Project_Manual.pdf)**. It includes 34 chapters and five appendices covering all application modules, role procedures, financial examples, independent reversal approval, statements, installation, configuration, deployment, backups, recovery, security and maintenance. The reference appendices describe 44 application models, 776 fields, 101 routes, 22 reports and the import schemas.

The illustrated edition contains **213 pages and 83 screenshots**, plus architecture and workflow diagrams. It uses the project's crimson, magenta, dark plum and pale pink palette. Its module screenshots use fictional records from an isolated training environment, including desktop/mobile views, statements and administrator review controls. Captured images are retained under `images/`, with captions and chapter mappings in [manual_illustrations.json](manual_illustrations.json).

An [HTML reading edition](SikaFriend_Complete_Project_Manual.html) contains the same content, with embedded pictures. Edit [complete_manual_content.html](complete_manual_content.html) and [complete_manual.css](complete_manual.css), then rebuild from the project root:

```bash
.venv/bin/python docs/manuals/build_complete_manual.py --refresh-reference
```

The reference refresh reads source definitions and forbids database connections. Ordinary rebuilds can omit `--refresh-reference` to use [project_reference.json](project_reference.json). Rendering embeds resources and makes no external downloads. [complete_manual_build.json](complete_manual_build.json) records page count, chapter pages and the PDF checksum. Review business procedures manually when code changes.

| Manual | Audience |
| --- | --- |
| [Administrator](roles/administrator.md) | System administrators and operations administrators |
| [Management](roles/management.md) | Managers with Admin Console Access and workforce role Management |
| [Agent](roles/agent.md) | Field, recovery, and portfolio agents |
| [Borrower](roles/borrower.md) | Customers using the self-service portal |
| [Dashboard and Applications](dashboard_operations.md) | Step-by-step instructions for every operational module |

The earlier [role-only PDF](SikaFriend_Role_Manuals.pdf) remains available as a historical short guide. Use the complete handbook for current financial controls, customer credit, statements and reversal procedures.

For technical deployment and complete module documentation, see [PROJECT_DOCUMENTATION.md](../../PROJECT_DOCUMENTATION.md).
