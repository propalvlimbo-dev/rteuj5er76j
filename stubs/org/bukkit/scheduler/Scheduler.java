package org.bukkit.scheduler;

import org.bukkit.plugin.Plugin;

/** LOCAL-BUILD STUB. Compile-only, never shaded into the jar. */
public interface Scheduler {
    BukkitTask runTask(Plugin plugin, Runnable task);

    BukkitTask runTaskTimerAsynchronously(Plugin plugin, Runnable task, long delay, long period);
}
