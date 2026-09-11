# m4-verdict-strategies graph

Two selectable routing strategies ("confidence": visible manager + explicit
verdict node; "background": silent manager, personas talk directly, "group"
delivers the verdict) share this exact node/edge shape — they differ only in
prompts and message visibility, not graph structure. Exported from the
default strategy ("confidence").

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	manager(manager)
	verdict(verdict)
	pragmatist(pragmatist)
	skeptic(skeptic)
	optimist(optimist)
	analyst(analyst)
	contrarian(contrarian)
	people_person(people_person)
	__end__([<p>__end__</p>]):::last
	__start__ --> manager;
	analyst --> manager;
	contrarian --> manager;
	manager -.-> __end__;
	manager -.-> analyst;
	manager -.-> contrarian;
	manager -.-> optimist;
	manager -.-> people_person;
	manager -.-> pragmatist;
	manager -.-> skeptic;
	manager -.-> verdict;
	optimist --> manager;
	people_person --> manager;
	pragmatist --> manager;
	skeptic --> manager;
	verdict --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
