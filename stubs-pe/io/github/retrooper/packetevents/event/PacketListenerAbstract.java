package io.github.retrooper.packetevents.event;

import io.github.retrooper.packetevents.event.impl.PacketPlayReceiveEvent;
import io.github.retrooper.packetevents.event.impl.PacketPlaySendEvent;

/** Compile-only стаб, сверен с исходниками packetevents v1.8.4. В jar не попадает. */
public abstract class PacketListenerAbstract {

    protected PacketListenerAbstract() {
    }

    public void onPacketPlayReceive(PacketPlayReceiveEvent event) {
    }

    public void onPacketPlaySend(PacketPlaySendEvent event) {
    }
}
