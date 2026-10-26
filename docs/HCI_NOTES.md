# HCI Design Notes - NEXACART

This document records *why* the interface of NEXACART looks and behaves the way it does.
It is written for the Human-Computer Interaction project report and can be used as the
design rationale chapter.

---

## 1. Users and tasks

| Persona            | Primary tasks                                           | Main risk for them                           |
| ------------------ | ------------------------------------------------------- | -------------------------------------------- |
| **Administrator**  | Create/inspect accounts, change roles, watch security activity | Locking themselves out of the platform       |
| **Seller**         | Register, secure the account, understand what they may and may not do | Accidentally reaching into another workspace |
| **Buyer**          | Register, sign in, change the password, review active devices | Being surprised by a blocked page            |
| **Arabic speaking visitor** | Read the same screens in Arabic, right to left | Losing the sense of place when the layout mirrors |

Three usability goals drove the design:

1. **Never leave the user guessing** about *why* something was refused.
2. **Never let a person reach the wrong workspace** - and if they try, refuse it clearly
   rather than with a raw server error.
3. **Make the security visible** - the user should be able to see who is signed in and
   end it.

A fourth goal was added when the interface was translated:

4. **One design for every language** - the layout must not be a second, lesser version
   of itself in another language.

---

## 2. Nielsen's ten usability heuristics

| # | Heuristic                        | How the interface satisfies it                                                                                                                                                       |
| - | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1 | Visibility of system status      | The role badge in the header always shows the current workspace; every action produces a coloured message ("Your password has been changed"); the language switcher always highlights the active language. |
| 2 | Match with the real world        | Plain words instead of jargon: "stock quantity" is never "inventory delta", "sign out" instead of "terminate session".                                                                |
| 3 | User control and freedom         | Every destructive action is reversible or confirmed: sessions can be revoked individually, a suspended account can be reactivated, the sign-out button is always one click away, and the language can be changed without leaving the page. |
| 4 | Consistency and standards        | One layout, one button style, one message style, one colour code for the three roles (indigo = administrator, orange = seller, green = buyer) on every page - and the same code in all three languages. |
| 5 | Error prevention                 | The server validates everything, the client validates as you type, a live password checklist shows the remaining requirements, and a generated password is offered.                   |
| 6 | Recognition rather than recall   | The dashboard names the current role, the header names the user, and the landing page shows the access matrix, so the user never has to remember the rules.                      |
| 7 | Flexibility and efficiency       | "Keep me signed in", a password generator, search and filters in the user table, pagination, and direct links to the detail page of a user.                                        |
| 8 | Aesthetic and minimalist design  | One primary action per screen, a restrained colour palette, generous whitespace, and no decoration that does not carry information.                                                    |
| 9 | Help users recover from errors   | Error messages state the problem, the reason and the next step, and they are placed next to the field that caused them; the summary at the top of the form links to the field.               |
| 10| Help and documentation           | The sign-in page explains what happens during a sign-in, the seller and buyer dashboards explain what their role may do, and `README.md` documents everything. |

---

## 3. Internationalisation and right-to-left support

### 3.1 Where the wording lives

Every visible string is a **key** in one of the three catalogues
(`nexacart/translations/en.json`, `fr.json`, `ar.json`). The templates ask for a dotted
key - `{{ t('login.title') }}` - and the server resolves it against the active locale.
There is no English text left in the HTML, and no wording in the Python code either.

Three rules keep the layer honest:

* **English is the fallback.** If a key is missing from `fr.json` or `ar.json`, the
  English wording is used instead of an empty label.
* **The key is the contract.** A key such as `role.buyer` or
  `audit.login_success` describes *what* is shown, never *how* it is worded, so it is
  stable across the three files. A test asserts that all three catalogues contain
  exactly the same set of keys.
* **Only the wording is translated, never the logic.** The password checklist carries
  `data-rule="min_length"`, the role names are looked up with `role.buyer`, and the
  audit log renders `audit.login_success`. The browser therefore checks the same rule
  in Arabic as in English.

### 3.2 How the language is chosen

1. The header shows three links - `EN`, `FR`, `AR`. The active one is highlighted.
2. Choosing one stores the locale in the signed session cookie and redirects back to the
   page the visitor came from, so reading a paragraph in another language does not
   interrupt the task.
3. The choice survives sign-in and sign-out (the session is rotated at that moment, so
   the locale is explicitly carried over).
4. If nothing was chosen yet, the browser's `Accept-Language` header decides - a
   French browser lands on the French interface without a click.
5. An unsupported locale falls back to English instead of raising an error.

### 3.3 Right-to-left

Arabic is a right-to-left script, and mirroring the interface is not a cosmetic detail:

* The server writes `<html lang="ar" dir="rtl">`, so the browser lays the document out
  from the right, and assistive technology is told the correct language.
* The stylesheet uses **logical properties** (`margin-inline-start`,
  `inset-inline-end`, `padding-inline-start`, `text-align: start`) instead of
  `left`/`right`. One rule therefore serves both directions, and no component drifts
  out of place when the language changes.
* Arabic letter spacing is switched off in the right-to-left block. Extra space between
  Arabic letters breaks the cursive ligatures and makes the text harder to read.
* The Arabic typeface stack prefers fonts that actually contain Arabic glyphs, and the
  line height is increased slightly because Arabic script needs more room.
* Numbers, dates and the "no-break" thousands separators follow the locale: French uses
  the narrow no-break space (`1 234,5`), Arabic uses Arabic-Indic digits
  (`١٬٢٣٤٫٥`), and the month names are written in the language of the page.

### 3.4 Why the whole interface is translated

A partial translation is a usability defect: the user reads a French page and suddenly
meets an English security warning, or an Arabic layout with an English-only button that
cannot be found because the label is a different word. Translating the *whole* surface -
including flash messages, validation errors, audit entries, role names and page titles -
costs little, because every string was already in one place in the template.

---

## 4. Accessibility (WCAG 2.1 AA orientation)

| Concern                | Implementation                                                                                                                    |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Keyboard operation     | All controls are native buttons, links and inputs; a skip link jumps to the main content; focus is visible through a 3 px outline.      |
| Screen readers         | Landmarks (`header`, `nav`, `main`, `footer`), labelled inputs, `aria-live="polite"` for messages, `aria-current="page"` for the active link, decorative icons hidden with `aria-hidden`. |
| Colour contrast        | Text colours were chosen for at least 4.5:1 on their background in the light theme, and a `prefers-contrast: more` block increases borders. |
| Colour independence    | The three roles are distinguished by text label *and* colour; status is written out ("Suspended"), never only coloured.                |
| Motion                 | `prefers-reduced-motion` disables transitions and smooth scrolling.                                                                  |
| Zoom / reflow          | The layout works from 320 px upwards and reflows to a single column on a phone.                                                    |
| Form errors            | Errors are described in text, linked from the error summary and attached to the input with `aria-describedby`.                     |
| Language of the page   | `lang` and `dir` are set by the server on every page, so a screen reader announces the right language and reads the Arabic text in the right direction. |
| Language switcher      | Every language link carries `hreflang`, `lang` and `dir`, and the active one is marked with `aria-current`.                          |

---

## 5. Design decisions worth defending

**Why is the role badge always in the header?**
It is the single most important piece of context in the whole application. A person who
wonders "am I in the right place?" should not have to open a menu to find out.

**Why does a blocked page explain itself instead of showing "403 Forbidden"?**
The technical status code tells the developer nothing. The user needs to know *which*
role is required and *what* to do next - therefore the page names the allowed roles,
repeats the role the user currently has, and offers a way back.

**Why is the administrator password change mandatory on the first sign-in?**
The seed password is printed in the terminal and in this document, so it is public. The
account is therefore locked into the security page until the owner replaces it.

**Why are sessions stored in the database instead of in the cookie?**
It is what makes "sign out of every other device" possible, allows an administrator to
end a suspended user's sessions immediately, and keeps the cookie free of any personal
data. The stored value is a hash, so a database leak cannot be replayed as a live
session.

**Why is the error message for a wrong password identical to the one for an unknown
account?**
A different message would turn the sign-in form into an account enumeration tool. The
helpful part ("5 attempts left") is about the account's counter, which only becomes
visible after the account has actually been targeted.

**Why is the password checklist live in the browser?**
Immediate feedback removes the trial-and-error loop of submitting a form and waiting for
a rejection. The same rules are still enforced on the server, so the checklist is a
convenience, never the guarantee.

**Why does the language switcher use links instead of a select box?**
A link can be reached with the keyboard, opened in a new tab and - most importantly - it
sends a plain `GET` request. Switching the language therefore never loses the content
the visitor was reading and never touches a form that is half filled in.

**Why is the language stored in the session and not in a cookie of its own?**
The session cookie is already signed by Flask and already travels with every request.
A second cookie would mean a second piece of state to protect for no benefit - and it
would let a visitor set an unsupported value that the application then has to defend
against.

---

## 6. Evaluation plan

The design was checked with the following methods; the same plan can be repeated once
the catalogue and the cart exist.

1. **Automated tests** - 53 unit and integration tests (`tests/test_app.py`) verify the
   functional, the access-control and the internationalisation requirements
   automatically: identical catalogue keys in all three languages, the language
   switcher, the right-to-left document attributes, locale aware number formatting and
   the absence of any release-stage wording in the interface.
2. **Heuristic evaluation** - the walk-through above, performed by the developer and a
   peer, using the ten heuristics.
3. **Task-based usability test** - five participants from the class are asked to:
   * register a buyer account and describe the password rules while doing it,
   * sign in and find the page that lists their active devices,
   * sign out one device and explain the effect,
   * switch the interface to Arabic and say whether anything moved unexpectedly,
   * as an administrator, find the account of a given user and change their role,
   * as a buyer, try to reach the product registration page and explain what happened.
4. **Metrics** - task completion, time on task, number of errors, SUS questionnaire and
   the "single ease of use question" (SEQ) for the sign-in and the role change.

### Known limitations to discuss in the report

* The sign-in lockout reveals that an account exists to someone who triggers five
  failures - a deliberate trade-off between security and helpfulness.
* The administrator statistics are simple counters; they should become charts once
  there is more data to show.
* Arabic was reviewed on a Windows desktop with the browser's own Arabic support. A
  study with native readers and a real screen reader (NVDA or VoiceOver) is the natural
  follow-up work.
* The interface has been tested with a screen reader only in part; a full WCAG audit
  would be the natural follow-up work.
