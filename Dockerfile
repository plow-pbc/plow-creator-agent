# Plow Creator and every agent it builds: one image, whose brain is data.
#
# An agent's persona comes from its `definition` setting in Plow, read at boot by
# cont-init's 10-pas-apply, so a created agent is a settings value on this one
# image, never an image of its own. An empty definition is Plow Creator itself.
#
# The tag is an immutable `base-<sha>` naming one commit of plow-pbc/plow-hermes-agent,
# the same base life-assistant-hermes-agent pins. It is never moved: every tenant VM
# inherits this exact filesystem while holding its owner's Plow credential.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-7422f99a12b15489408cacfbf884d745d4eccab5@sha256:efe3b0fdf97601c8a1b14b3faf31d0c919116c40687c5252cf501e5f6ff19898

# Root-owned and outside every home, so no turn can rewrite what the next boot runs.
# Modes are set in their own step: `COPY --chmod` is BuildKit-only (plow-hermes-agent README).
COPY runtime/creator.md runtime/pas.py /opt/plow-creator/
COPY runtime/10-pas-apply /etc/cont-init.d/10-pas-apply
RUN chmod 0755 /opt/plow-creator /etc/cont-init.d/10-pas-apply \
 && chmod 0644 /opt/plow-creator/creator.md /opt/plow-creator/pas.py
COPY LICENSE NOTICE /usr/share/doc/plow-creator-agent/
