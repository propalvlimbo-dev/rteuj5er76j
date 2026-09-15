package ru.elytrix.efc.packet;

import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Пакетные данные игрока. Пишет netty-поток, читает главный поток —
 * только volatile и потокобезопасная очередь. Флагов отсюда нет:
 * решения принимают проверки в главном потоке.
 */
public final class PacketData {

    private final Queue<Long> flying = new ConcurrentLinkedQueue<>();
    volatile double lastX;
    volatile double lastY;
    volatile double lastZ;
    volatile float lastYaw;
    volatile float lastPitch;
    volatile boolean lastGround;
    volatile long lastFlyingMs;
    volatile long lastAttackMs;
    volatile int lastAttackEntity = -1;
    volatile long lastSwingMs;

    /** Вызывать из netty-потока. */
    public void flying(double x, double y, double z, float yaw, float pitch,
            boolean ground, boolean moving, boolean rotating) {
        if (moving) {
            lastX = x;
            lastY = y;
            lastZ = z;
        }
        if (rotating) {
            lastYaw = yaw;
            lastPitch = pitch;
        }
        lastGround = ground;
        lastFlyingMs = System.currentTimeMillis();
        flying.add(lastFlyingMs);
    }

    /** Вызывать из netty-потока. */
    public void attack(int entityId) {
        lastAttackEntity = entityId;
        lastAttackMs = System.currentTimeMillis();
    }

    /** Вызывать из netty-потока. */
    public void swing() {
        lastSwingMs = System.currentTimeMillis();
    }

    /** Главный поток: вычистить старше секунды и посчитать Flying. */
    public int pruneAndCountFlying(long now) {
        Long head;
        while ((head = flying.peek()) != null && now - head > 1000) {
            flying.poll();
        }
        return flying.size();
    }

    /** Главный поток: есть ли свежие пакетные данные? */
    public boolean hasRecentFlying(long now, long maxAgeMs) {
        return lastFlyingMs != 0 && now - lastFlyingMs <= maxAgeMs;
    }

    public float getLastYaw() {
        return lastYaw;
    }

    public float getLastPitch() {
        return lastPitch;
    }

    public long getLastFlyingMs() {
        return lastFlyingMs;
    }
}
