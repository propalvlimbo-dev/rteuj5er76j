package ru.elytrix.efc.packet;

import io.github.retrooper.packetevents.event.PacketListenerAbstract;
import io.github.retrooper.packetevents.event.impl.PacketPlayReceiveEvent;
import io.github.retrooper.packetevents.packettype.PacketType;
import io.github.retrooper.packetevents.packetwrappers.play.in.flying.WrappedPacketInFlying;
import io.github.retrooper.packetevents.packetwrappers.play.in.useentity.WrappedPacketInUseEntity;
import io.github.retrooper.packetevents.packetwrappers.play.in.useentity.WrappedPacketInUseEntity.EntityUseAction;
import io.github.retrooper.packetevents.utils.vector.Vector3d;
import org.bukkit.entity.Player;

/**
 * Слушатель входящих пакетов (API packetevents 1.8.x).
 * Только записывает: Flying-поток, атаки, взмахи. Всё в try/catch —
 * netty-поток умирать не должен. Флаги — только из главного потока.
 */
public final class PlayListener extends PacketListenerAbstract {

    private final PacketManager manager;

    public PlayListener(PacketManager manager) {
        this.manager = manager;
    }

    @Override
    public void onPacketPlayReceive(PacketPlayReceiveEvent event) {
        try {
            Player player = event.getPlayer();
            if (player == null) {
                return;
            }
            byte id = event.getPacketId();
            if (id == PacketType.Play.Client.POSITION
                    || id == PacketType.Play.Client.POSITION_LOOK
                    || id == PacketType.Play.Client.LOOK
                    || id == PacketType.Play.Client.FLYING) {
                WrappedPacketInFlying flying = new WrappedPacketInFlying(event.getNMSPacket());
                Vector3d position = flying.getPosition();
                manager.flying(player, position.x, position.y, position.z,
                        flying.getYaw(), flying.getPitch(), flying.isOnGround(),
                        flying.isMoving(), flying.isRotating());
            } else if (id == PacketType.Play.Client.USE_ENTITY) {
                WrappedPacketInUseEntity use = new WrappedPacketInUseEntity(event.getNMSPacket());
                if (use.getAction() == EntityUseAction.ATTACK) {
                    manager.attack(player, use.getEntityId());
                }
            } else if (id == PacketType.Play.Client.ARM_ANIMATION) {
                manager.swing(player);
            }
        } catch (Throwable ignored) {
            // Пакетный слой никогда не роняет связь игрока.
        }
    }
}
