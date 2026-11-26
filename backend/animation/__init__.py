"""The 2D animation engine: from a science question to an animated Short waiting for approval.

- animation/        research, script, storyboard, voices, timing, quality, publishing, the panel
- animation/shared/ general-purpose pieces: settings, source reading, the voice call, probes...
- ../channels/      one profile per channel (brand, cast, voices, format, limits)
- ../data/          each channel's own database and files (not in git)
- ../../animator/   the Godot project that draws the scenes
- ../../renderer/   the Remotion project that lays captions and titles over them

Claude never writes code for the renderer. It writes a storyboard: JSON that only names resources
registered in animator/library/manifest.json. The storyboard is validated here before anything is
drawn, and the Godot director refuses a plan that names something it does not have.
"""
