---
name: video_editing
description: AI-assisted video editing workflows for cutting, structuring, and augmenting real footage through FFmpeg, Remotion, and post-production tools
alwaysLoad: false
---

# Video Editing

AI-assisted editing for real footage. Not generation from prompts. Editing existing video fast.

## When to Use

- Editing, cutting, or structuring video footage
- Turning long recordings into short-form content
- Building vlogs, tutorials, or demo videos from raw capture
- Adding overlays, subtitles, music, or voiceover
- Reframing video for different platforms

## Core Thesis

AI video editing is useful when you stop asking it to create the whole video and start using it to compress, structure, and augment real footage. The value is compression, not generation.

## The Pipeline

```
Raw footage / Screen recording
  -> Organization and planning
  -> FFmpeg (deterministic cuts)
  -> Remotion (programmable composition)
  -> Generated assets (voiceover, music)
  -> Final polish (Descript / CapCut)
```

Each layer has a specific job. Do not try to make one tool do everything.

## Layer 1: Capture

- **Screen recordings:** Polished captures for app demos, coding sessions
- **Raw camera footage:** Vlogs, interviews, events
- **Desktop capture:** Session recordings with context

## Layer 2: Organization

Use trio to:
- Transcribe and label: generate transcript, identify topics
- Plan structure: decide what stays, gets cut, and the order
- Identify dead sections: pauses, tangents, repeated takes
- Generate edit decision list: timestamps for cuts
- Scaffold FFmpeg and Remotion code

```
Example: "Here's the transcript of a 4-hour recording. Identify the 8 strongest
segments for a 24-minute vlog. Give me FFmpeg cut commands for each segment."
```

## Layer 3: Deterministic Cuts (FFmpeg)

### Extract segment
```bash
ffmpeg -i raw.mp4 -ss 00:12:30 -to 00:15:45 -c copy segment_01.mp4
```

### Batch cut from edit decision list
```bash
while IFS=, read -r start end label; do
  ffmpeg -i raw.mp4 -ss "$start" -to "$end" -c copy "segments/${label}.mp4"
done < cuts.txt
```

### Concatenate segments
```bash
for f in segments/*.mp4; do echo "file '$f'"; done > concat.txt
ffmpeg -f concat -safe 0 -i concat.txt -c copy assembled.mp4
```

### Create proxy for faster editing
```bash
ffmpeg -i raw.mp4 -vf "scale=960:-2" -c:v libx264 -preset ultrafast -crf 28 proxy.mp4
```

### Extract audio for transcription
```bash
ffmpeg -i raw.mp4 -vn -acodec pcm_s16le -ar 16000 audio.wav
```

### Normalize audio
```bash
ffmpeg -i segment.mp4 -af loudnorm=I=-16:TP=-1.5:LRA=11 -c:v copy normalized.mp4
```

## Layer 4: Programmable Composition (Remotion)

Use Remotion for:
- Text overlays, branding, lower thirds
- Data visualizations and animated numbers
- Motion graphics and transitions
- Composable, reusable scene templates
- Product demos with annotated screenshots

```tsx
import { AbsoluteFill, Sequence, Video } from "remotion";

export const Composition: React.FC = () => (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={300}>
      <Video src="/segments/intro.mp4" />
    </Sequence>
    <Sequence from={30} durationInFrames={90}>
      <TitleOverlay text="The AI Editing Stack" />
    </Sequence>
  </AbsoluteFill>
);
```

Render: `npx remotion render src/index.ts Composition output.mp4`

## Layer 5: Generated Assets

Generate only what you need:
- **Voiceover:** ElevenLabs or similar TTS APIs
- **Music:** AI music generation for background tracks
- **Sound effects:** Transition sounds, ambient audio
- **Insert shots:** AI-generated thumbnails or b-roll that doesn't exist

## Layer 6: Final Polish

Use a traditional editor (Descript, CapCut) for:
- **Pacing:** adjust cuts that feel wrong
- **Captions:** auto-generated, then manually cleaned
- **Color grading:** basic correction and mood
- **Final audio mix:** balance voice, music, SFX
- **Export:** platform-specific formats

This is where taste lives. AI clears the repetitive work. You make the final calls.

## Social Media Reframing

| Platform | Aspect Ratio | Resolution |
|----------|-------------|------------|
| YouTube | 16:9 | 1920x1080 |
| TikTok / Reels | 9:16 | 1080x1920 |
| Instagram Feed | 1:1 | 1080x1080 |
| Twitter/X | 16:9 or 1:1 | 1280x720 |

```bash
# 16:9 to 9:16 (center crop)
ffmpeg -i input.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" vertical.mp4

# 16:9 to 1:1 (center crop)
ffmpeg -i input.mp4 -vf "crop=ih:ih,scale=1080:1080" square.mp4
```

## Scene Detection

```bash
# Detect scene changes
ffmpeg -i input.mp4 -vf "select='gt(scene,0.3)',showinfo" -vsync vfr -f null - 2>&1 | grep showinfo

# Find silent segments (for cutting dead air)
ffmpeg -i input.mp4 -af silencedetect=noise=-30dB:d=2 -f null - 2>&1 | grep silence
```

## Key Principles

1. **Edit, don't generate.** This workflow is for cutting real footage.
2. **Structure before style.** Get the story right before touching visuals.
3. **FFmpeg is the backbone.** Boring but critical for processing.
4. **Remotion for repeatability.** If you'll do it more than once, make it a component.
5. **Generate selectively.** Only use AI generation for assets that don't exist.
6. **Taste is the last layer.** AI clears repetitive work. You make final creative calls.
