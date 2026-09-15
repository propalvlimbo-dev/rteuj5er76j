package io.github.retrooper.packetevents.packetwrappers.play.in.useentity;

import io.github.retrooper.packetevents.packetwrappers.NMSPacket;

/** Compile-only стаб, сверен с исходниками packetevents v1.8.4. В jar не попадает. */
public final class WrappedPacketInUseEntity {

    public enum EntityUseAction {
        INTERACT, ATTACK, INTERACT_AT
    }

    public WrappedPacketInUseEntity(NMSPacket packet) {
    }

    public EntityUseAction getAction() {
        return null;
    }

    public int getEntityId() {
        return 0;
    }
}
