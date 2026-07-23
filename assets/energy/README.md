# Pilot energy artwork

This directory is the canonical source for the local energy-scene artwork that
is packaged into Pilot clients. Runtime clients must never depend on these
files over the network; each platform receives a build-time copy appropriate
to its resource system.

## House scenes

The four 1536x1024 house images were supplied by the owner and map as follows:

| File | Lighting | Tesla |
| --- | --- | --- |
| `house-day.png` | Day | Absent |
| `house-day-tesla.png` | Day | Present |
| `house-night.png` | Night | Absent |
| `house-night-tesla.png` | Night | Present |

Presence follows the configured vehicle-connected binary sensor. Vehicle power
does not choose the image. Day/night follows `scene.is_day` from Pilot Core and
falls back to solar production only when an older Core omits the scene field.

## Server rack

`server-rack.png` was generated with OpenAI image generation on 2026-07-22 and
then converted from a flat magenta key to a transparent PNG. Prompt:

> Create a single premium isometric home server rack matching the polished,
> photorealistic-isometric lighting of the supplied James House day scene. Dark
> graphite cabinet, visible switches and servers, neat blue and amber patch
> cables, small blue/green/amber status lights, clean front three-quarter view,
> no text, no logo, no cast shadow. Isolate it on one perfectly flat #ff00ff
> chroma-key background with no gradient or contamination.

The raster remains static. Each client draws independently timed LED overlays
so activity stays crisp, accessible and power-efficient without an animated
GIF. Clients must stop decorative motion when reduced-motion is enabled.
