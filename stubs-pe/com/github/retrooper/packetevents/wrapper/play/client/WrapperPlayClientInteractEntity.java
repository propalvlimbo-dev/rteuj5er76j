package com.github.retrooper.packetevents.wrapper.play.client;

import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.util.Vector3d;
import java.util.Optional;

/** Compile-only стаб, сверен с исходниками packetevents v2.13.0. В jar не попадает. */
public class WrapperPlayClientInteractEntity {

    public enum InteractAction {
        INTERACT, ATTACK, INTERACT_AT
    }

    public WrapperPlayClientInteractEntity(PacketReceiveEvent event) {
    }

    public int getEntityId() {
        return 0;
    }

    public InteractAction getAction() {
        return null;
    }

    public Optional<Boolean> isSneaking() {
        return Optional.empty();
    }

    public Vector3d getLocation() {
        return null;
    }
}
