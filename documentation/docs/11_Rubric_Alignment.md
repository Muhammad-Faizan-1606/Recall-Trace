# Rubric alignment and submission checklist

Source S01 is the supplied course rubric. Its eight criteria total 100 marks. The 40 related table/model minimum is a hard submission requirement. This matrix maps intended implementation and future proof; it does not award a grade or certify that those features already exist.

| Criterion | Marks | Planned implementation | Evidence | Planned tests |
| --- | --- | --- | --- | --- |
| Project Setup and Structure | 10 | Virtual environment; accurate locked requirements.txt; app factory; blueprints; migrations; separate configuration. | README setup transcript; dependency lock; app/__init__.py; app/extensions.py; migrations; clean startup. | T056 T058 |
| Routing and View Functions | 15 | Focused route functions with GET forms and POST mutations; UUID converters; permission and company guards. | docs/04_Routes_and_Screens.md; application route map; 404 405 409 and PRG demonstrations. | T001 T007 T013 T054 |
| Templates and Jinja2 Usage | 15 | Shared base layout; extends and block; macros for fields tables pagination; explicit loops and conditionals. | templates/base.html; macros/forms.html; macros/pagination.html; template review and narrow viewport screenshots. | T031 T055 |
| Database Integration and CRUD | 20 | 100 related model design; Core 72 and Expanded 28; primary keys foreign keys checks unique constraints; full mapped business CRUD. | docs/03_Database_Design.md; source/schema.json; docs/05_CRUD_Coverage.md; ERDs; migrated model inventory. | T011 T012 T014 T018 T026 T056 T057 |
| Forms Validation Cookies and Sessions | 15 | Flask WTF server validation; business constraints; shared server sessions; CSRF; flash messages; 303 Post Redirect Get. | forms and domain validators; session settings; invalid input and cookie inspection; repeat POST demonstration. | T005 T006 T009 T013 T054 |
| Code Quality and Organization | 10 | Small views; domain services; explicit transaction ownership; typed naming conventions; Ruff and reviewed migrations. | Module boundaries; review checklist; lint output; readable service implementation and no duplicated layouts. | T057 |
| Functionality and Testing | 10 | Complete described release; PostgreSQL integration and concurrency tests; browser workflow and operational checks. | docs/08_Test_Plan.md; requirements traceability; test results; documented defects and full demo transcript. | T001 T016 T022 T033 T059 T060 T061 T062 |
| Documentation | 5 | Purpose setup environment variables migrations seed data run commands role guide test guide and known limitations. | This specification; developer pack README and planned application README contract; fresh teammate setup. | T056 T061 |

## Submission checks

- Selected release tables and ORM classes match the implemented feature inventory and exceed the 40-model minimum.
- All related business screens demonstrate permitted CRUD with validated forms and correct methods.
- Jinja inheritance macros loops and conditionals are shown with actual records.
- Successful forms use flash feedback and Post Redirect Get; CSRF and session behavior are demonstrated.
- The application runs from a clean setup using accurate dependency environment migration and seed instructions.
- Meaningful tests run against the actual database behavior and the full recall workflow.
- README identifies supported features configured integrations limitations and acknowledgements.
- Protected-history CRUD interpretation and the separately issued submission rules are recorded.

The documentation criterion can be prepared now; setup functionality security and testing criteria require implementation and actual verification. Tables above describe that work precisely so later evidence can be attached.
