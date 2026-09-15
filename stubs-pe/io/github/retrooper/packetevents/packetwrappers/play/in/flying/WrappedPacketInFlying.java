package io.github.retrooper.packetevents.packetwrappers.play.in.flying;

import io.github.retrooper.packetevents.packetwrappers.NMSPacket;
import io.github.retrooper.packetevents.utils.vector.Vector3d;

/** Compile-only стаб, сверен с исходниками packetevents v1.8.4. В jar не попадает. */
public class WrappedPacketInFlying {

    public WrappedPacketInFlying(NMSPacket packet) {
    }

    public Vector3d getPosition() {
        return null;
    }

    public float getYaw() {
        return 0;
    }

    public float getPitch() {
        return 0;
    }

    public boolean isOnGround() {
        return false;
    }

    public boolean isMoving() {
        return false;
    }

    public boolean isRotating() {
        return false;
    }
}
