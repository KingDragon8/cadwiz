# Reproducible beta exercise

After connecting your assistant to CADWiz, paste:

> Create an editable 3:1 herringbone gearbox in my existing FreeCAD window.
> Use 20/60 teeth, normal module 2 mm, normal pressure angle 20 degrees, helix
> angle 25 degrees, and a 20 mm face width excluding hubs. Use smooth native
> opposite-hand helical sweeps meeting at the center, not a sparse ruled loft.
> Input shaft: 15 mm. Output shaft: 8 mm with an 8.35 mm gear bore. Output hub:
> 22 mm OD, projecting 9 mm per side, with two M4 x 0.7 grub-screw locations;
> identify tap pilots if thread helices are omitted. Use 608 output bearings;
> assume 6002 input bearings. Start with an adjustable 0.20 mm extra center
> distance for prototype running clearance. Include a rounded enclosure,
> mounting feet, bearing retention, shaft collars and removable clear cover.
> Keep native parametric history and named dimensions. State assumptions.
>
> Validate the generated tooth sections between construction profiles in both
> halves against the expected rotated involute, check sampled mesh clearance,
> and inspect isolated shaded teeth and edge views. Save, reopen and recompute.
> If compatible mechanical animation is available, show counter-rotation at 3:1
> without altering saved manufacturing positions. Report unsupported capabilities
> and physical tests still needed. Preserve other open documents and save as
> Beta_Herringbone_Gearbox. Finish by showing the actual native viewport.

This is an exercise specification, not a bundled CAD model or a promise that a
particular assistant will produce a qualified assembly in one attempt. The
synthetic CI fixture tests the gear pair and its editability, not the complete
housing or a live paid AI conversation.
