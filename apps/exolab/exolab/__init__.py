"""Exo Lab core: engine-free physics for exoskeletons, cyber limbs and mechs.

Everything here is plain Python plus numpy, reads only the JSON in ``data/``
and the character files, and knows nothing about the web page or any game
engine. Units are SI; angles are degrees in data and in API results, radians
inside the maths.

Frames:
    * Body frame (API output, VRM normalised humanoid): +X the subject's left,
      +Y up, +Z forward. Positions are metres from the character's feet.
    * Arm frame (inside the maths, ISB style, right arm): x forward, y up,
      z to the right (lateral). ``vec.arm_to_body`` converts.
"""
