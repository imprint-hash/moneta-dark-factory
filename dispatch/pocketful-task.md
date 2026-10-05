Build the pocketful track, all four stages in order, as a dark-factory run. Coordinate @builder @examiner @guest.

Workspace root: /home/ubuntu/work
Working folder (specifications and harness): /home/ubuntu/work/dark-factory-wearedevs
Track: pocketful
Specifications: /home/ubuntu/work/dark-factory-wearedevs/pocketful/spec/stage-1.md, stage-2.md, stage-3.md, stage-4.md
Result repository: /home/ubuntu/work/band-work/result

Implement stage 1 fully in /home/ubuntu/work/band-work/result/stage-1/. When it is accepted, copy that folder to stage-2/ (remove any .git inside the copy) and extend it to the stage-2 specification; then the same for stage-3/ and stage-4/. Each folder solves its own stage and every earlier one, and not the next one.

Check a stage with:
cd /home/ubuntu/work/dark-factory-wearedevs && . .venv/bin/activate && python -m harness run --track pocketful --repo /home/ubuntu/work/band-work/result --stage N --out /home/ubuntu/work/band-work/checks/<new-unique-name>
Run the final check of each stage with --mode isolated as well.

Product direction for the screens (from stage 2):
- A calm, trustworthy consumer money app. Dark navy-to-black background with a soft blue glow; white sans-serif type; generous rounded cards.
- Two accent colours with fixed meaning: periwinkle blue (#6E8CF0) for money in and for primary actions; coral pink (#E06A7A) for money out.
- Home: a large rounded balance card where available funds are the biggest number on the screen, with total and held funds smaller beneath; a row of round contact avatars showing initials and handles for quick paying, plus an Add button; the activity feed below, each row with a round coloured icon, who, when, and the amount in blue (in) or coral (out), and a public or private tag.
- Split is a highlight: amount and handles in one card, and every participant's share shown live as a row with their initials before anything is sent.
- Every state the specification names (loading, sent, refused, uncertain, empty) gets its own clear colour and plain words.
- On phones, a bottom navigation bar; on desktop, the same sections in a side menu. No horizontal scrolling at 375 pixels.

Finish each stage fully before the next. Report the outcome of every stage.
