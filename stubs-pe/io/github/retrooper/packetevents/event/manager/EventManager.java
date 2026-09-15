package io.github.retrooper.packetevents.event.manager;

import io.github.retrooper.packetevents.event.PacketListenerAbstract;

/** Compile-only стаб, сверен с исходниками packetevents v1.8.4. В jar не попадает. */
public interface EventManager {

    EventManager registerListener(PacketListenerAbstract listener);
}
