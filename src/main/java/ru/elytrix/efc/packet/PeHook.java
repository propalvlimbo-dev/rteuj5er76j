package ru.elytrix.efc.packet;

import com.github.retrooper.packetevents.PacketEvents;
import org.bukkit.entity.Player;

/**
 * Единственное место прямых касаний PacketEvents (API 2.x).
 * Класс грузится лениво — только когда плагин есть на сервере
 * (PacketManager проверяет заранее).
 */
public final class PeHook {

    private PeHook() {
    }

    public static void register(PacketManager manager) {
        PacketEvents.getAPI().getEventManager().registerListener(new PlayListener(manager));
    }

    public static int ping(Player player) {
        try {
            return PacketEvents.getAPI().getPlayerManager().getPing(player);
        } catch (Throwable ignored) {
            return -1;
        }
    }
}
