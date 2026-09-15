package ru.elytrix.efc.packet;

import com.github.retrooper.packetevents.event.PacketListenerAbstract;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.packettype.PacketTypeCommon;
import com.github.retrooper.packetevents.protocol.world.Location;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientInteractEntity.InteractAction;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientNameItem;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientPlayerFlying;
import java.util.UUID;
import org.bukkit.entity.Player;
import ru.elytrix.efc.grim.GrimBridge;

/**
 * Слушатель входящих пакетов (API packetevents 2.x).
 * Пишет данные для EFC-проверок; сырые пакеты уходят в дословный код Grim.
 * Всё в try/catch — netty-поток умирать не должен.
 */
public final class PlayListener extends PacketListenerAbstract {

    private final PacketManager manager;

    public PlayListener(PacketManager manager) {
        this.manager = manager;
    }

    @Override
    public void onPacketReceive(PacketReceiveEvent event) {
        try {
            PacketTypeCommon type = event.getPacketType();
            if (type == PacketType.Play.Client.PLAYER_FLYING
                    || type == PacketType.Play.Client.PLAYER_POSITION
                    || type == PacketType.Play.Client.PLAYER_ROTATION
                    || type == PacketType.Play.Client.PLAYER_POSITION_AND_ROTATION) {
                handleFlying(event);
            } else if (type == PacketType.Play.Client.INTERACT_ENTITY) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                WrapperPlayClientInteractEntity use = new WrapperPlayClientInteractEntity(event);
                if (use.getAction() == InteractAction.ATTACK) {
                    manager.attack(player, use.getEntityId());
                }
            } else if (type == PacketType.Play.Client.ANIMATION) {
                Player player = event.getPlayer();
                if (player == null) {
                    return;
                }
                manager.swing(player);
            } else if (type == PacketType.Play.Client.CREATIVE_INVENTORY_ACTION
                    || type == PacketType.Play.Client.CLIENT_SETTINGS
                    || type == PacketType.Play.Client.CLICK_WINDOW
                    || type == PacketType.Play.Client.TAB_COMPLETE
                    || type == PacketType.Play.Client.ENTITY_ACTION
                    || type == PacketType.Play.Client.PONG
                    || type == PacketType.Play.Client.WINDOW_CONFIRMATION) {
                GrimBridge.dispatchPacket(event);
            } else if (type == PacketType.Play.Client.NAME_ITEM) {
                handleNameItem(event);
            }
        } catch (Throwable ignored) {
            // Пакетный слой никогда не роняет связь игрока.
        }
    }

    private void handleFlying(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        UUID id = player.getUniqueId();
        WrapperPlayClientPlayerFlying flying;
        try {
            flying = new WrapperPlayClientPlayerFlying(event);
        } catch (Throwable malformed) {
            event.setCancelled(true);
            manager.reportViolation(id, "Crash.C", "malformed");
            return;
        }
        Location location = flying.getLocation();
        manager.flying(player, location.getX(), location.getY(), location.getZ(),
                location.getYaw(), location.getPitch(), flying.isOnGround(),
                flying.hasPositionChanged(), flying.hasRotationChanged());
        GrimBridge.dispatchPacket(event);
    }

    private void handleNameItem(PacketReceiveEvent event) {
        Player player = event.getPlayer();
        if (player == null) {
            return;
        }
        try {
            String name = new WrapperPlayClientNameItem(event).getItemName();
            // EFC ExploitA: имя в наковальне длиннее 50.
            if (name != null && name.length() > 50) {
                event.setCancelled(true);
                manager.reportViolation(player.getUniqueId(), "Exploit.A",
                        "len=" + name.length());
            }
        } catch (Throwable malformed) {
            event.setCancelled(true);
            report(event, "Exploit.A", "malformed");
        }
    }

    private void report(PacketReceiveEvent event, String checkId, String details) {
        try {
            Player player = event.getPlayer();
            if (player != null) {
                manager.reportViolation(player.getUniqueId(), checkId, details);
            }
        } catch (Throwable ignored) {
        }
    }
}
