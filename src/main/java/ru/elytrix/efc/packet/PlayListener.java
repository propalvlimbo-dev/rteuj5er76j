package ru.elytrix.efc.packet;

import com.github.retrooper.packetevents.event.PacketListenerAbstract;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.world.Location;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity.InteractAction;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientPlayerFlying;
import org.bukkit.entity.Player;

/**
 * Слушатель входящих пакетов (API packetevents 2.x).
 * Только записывает: Flying-поток, атаки, взмахи. Всё в try/catch —
 * netty-поток умирать не должен. Флаги — только из главного потока.
 */
public final class PlayListener extends PacketListenerAbstract {

    private final PacketManager manager;

    public PlayListener(PacketManager manager) {
        this.manager = manager;
    }

    @Override
    public void onPacketReceive(PacketReceiveEvent event) {
        try {
            if (event.getPacketType() == PacketType.Play.Client.PLAYER_FLYING
                    || event.getPacketType() == PacketType.Play.Client.PLAYER_POSITION
                    || event.getPacketType() == PacketType.Play.Client.PLAYER_ROTATION
                    || event.getPacketType() == PacketType.Play.Client.PLAYER_POSITION_AND_ROTATION) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                WrapperPlayClientPlayerFlying flying = new WrapperPlayClientPlayerFlying(event);
                Location location = flying.getLocation();
                manager.flying(player, location.getX(), location.getY(), location.getZ(),
                        location.getYaw(), location.getPitch(), flying.isOnGround(),
                        flying.hasPositionChanged(), flying.hasRotationChanged());
            } else if (event.getPacketType() == PacketType.Play.Client.INTERACT_ENTITY) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                WrapperPlayClientInteractEntity use = new WrapperPlayClientInteractEntity(event);
                if (use.getAction() == InteractAction.ATTACK) {
                    manager.attack(player, use.getEntityId());
                }
            } else if (event.getPacketType() == PacketType.Play.Client.ANIMATION) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                manager.swing(player);
            }
        } catch (Throwable ignored) {
            // Пакетный слой никогда не роняет связь игрока.
        }
    }
}
