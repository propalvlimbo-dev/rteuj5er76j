package ru.elytrix.efc.data;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.bukkit.entity.Player;
import ru.elytrix.efc.ElytrixFuckCheats;

/** Все данные игрока для античита: VL, тайминги, версия клиента. */
public final class PlayerData {

    private final ElytrixFuckCheats plugin;
    private final UUID uuid;
    private final Map<String, Double> vl = new HashMap<>();
    private final Map<String, Long> lastFlag = new HashMap<>();
    private final long joinTime = System.currentTimeMillis();

    /** Версия клиента (ViaVersion protocol id), -1 = неизвестна. Заполнит пакетный слой. */
    private volatile int clientVersion = -1;

    /** Момент последнего удара в ближнем бою, 0 = не бил. */
    private volatile long lastAttackTime;

    public PlayerData(ElytrixFuckCheats plugin, UUID uuid) {
        this.plugin = plugin;
        this.uuid = uuid;
    }

    public UUID getUuid() {
        return uuid;
    }

    public Player getPlayer() {
        return plugin.getServer().getPlayer(uuid);
    }

    public long getJoinTime() {
        return joinTime;
    }

    public int getClientVersion() {
        return clientVersion;
    }

    public void setClientVersion(int clientVersion) {
        this.clientVersion = clientVersion;
    }

    public long getLastAttack() {
        return lastAttackTime;
    }

    public void setLastAttack(long lastAttackTime) {
        this.lastAttackTime = lastAttackTime;
    }

    public synchronized double addVl(String checkId, double amount) {
        double value = Math.max(0, vl.getOrDefault(checkId, 0.0) + amount);
        vl.put(checkId, value);
        lastFlag.put(checkId, System.currentTimeMillis());
        return value;
    }

    public synchronized double getVl(String checkId) {
        return vl.getOrDefault(checkId, 0.0);
    }

    public synchronized Map<String, Double> getVlSnapshot() {
        return Collections.unmodifiableMap(new HashMap<>(vl));
    }

    /** Затухание VL — честный игрок со временем «отмывается». */
    public synchronized void decay(double amount) {
        if (amount <= 0) {
            return;
        }
        for (Map.Entry<String, Double> entry : vl.entrySet()) {
            double value = entry.getValue() - amount;
            entry.setValue(Math.max(0, value));
        }
    }
}
