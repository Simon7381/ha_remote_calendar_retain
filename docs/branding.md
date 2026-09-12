# Integration icon

The icon replaces the supplied calendar image's padlock with a brain, retaining its flat cyan style. The image was edited with the built-in image generation tool, followed by user-authorized local processing to remove the opaque checkerboard and export transparent PNGs.

Files used by Home Assistant:

- `custom_components/ha_remote_calendar_retain/brand/icon.png`: 256 × 256.
- `custom_components/ha_remote_calendar_retain/brand/icon@2x.png`: 512 × 512.

Both files use cyan `#00AEEF` with an alpha channel. Home Assistant's brand image fallback uses these icons for light and dark themes and for logo requests; no manifest image setting is needed. See the [Home Assistant brand image documentation](https://developers.home-assistant.io/docs/core/integration/brand_images/).

## Generation prompts

Initial edit prompt:

> Use case: precise-object-edit. Asset type: Home Assistant integration icon, square transparent PNG. Input image 1 is the EDIT TARGET. Replace ONLY the padlock at the bottom right with a recognizable stylized human brain icon. Preserve the existing cyan blue (#00AEEF approximately, match the source), flat Material Design style, thick calendar outline, top tabs, calendar position and proportions. The brain occupies the same bottom-right badge area as the padlock and has a rounded two-hemisphere silhouette with a few clear transparent curved folds and central division, legible at small icon sizes. Preserve the clear gap separating badge from calendar frame. Remove all padlock shapes. Single flat cyan color, crisp edges, no gradients, shadows, text or added decoration. Background and all negative spaces must be genuinely transparent, not black or white, for use on light and dark Home Assistant backgrounds. Export square PNG, ideally 512x512.

Final generation prompt:

> Create the final transparent cutout asset from this reference. Remove the gray checkerboard completely. The checkerboard is unwanted image content, not transparency. Output a transparent-background PNG showing ONLY the solid bright cyan calendar outline and solid bright cyan brain at bottom right. Preserve these shapes. Use actual alpha transparency in every background pixel including holes. Do not draw any checkerboard, texture, shadows, gray, black or white background. Clean flat solid-color app icon, square canvas.

The generator still returned an opaque checkerboard. Local processing extracted the cyan silhouette using the blue-minus-red channel difference, removed the gray background, applied a solid cyan foreground, and downsampled the alpha mask with Lanczos filtering. The exported images were inspected on white and dark backgrounds and checked for fully transparent background pixels.
