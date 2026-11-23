# Model-aware Animate

Animate selects the current document only. It never opens a different project to find a familiar mechanism.

- Existing dispenser and phone-arm motion adapters are retained.
- Two visible external involute gears are recognized from their actual tooth counts, module, parallel axes and compatible center distance. They counter-rotate at the tooth-count ratio. Coaxial shafts, collars and spacers follow; housings and bearings remain stationary.
- Other visible solid, surface, wire or mesh models use a camera turntable. The button says **Stop turntable**, and the tooltip explains that mechanical motion is not defined. This does not claim inferred joints or physical simulation.
- An empty/hidden model receives an instruction to open a visible 3D model, before any view activation or assembly-state change.
- Stop and document switching restore the temporary view. Neither mode changes manufacturing placements, parameters or saved geometry.

`tests/test_general_motion.py` covers data-driven gear selection, ratio, hidden components, attachment ownership, temporary-node cleanup, camera restoration and static-model fallback. Existing mechanism tests remain in place. The local development tree additionally retains its scanner and leg adapters.

The live acceptance macro exercises the actual button on a generic box and the 20/60-tooth gearbox, captures two native frames, and checks unchanged model placements and file bytes. A passing automated suite does not substitute for that native-session result.
