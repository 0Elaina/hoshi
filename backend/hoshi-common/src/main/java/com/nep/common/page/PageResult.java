package com.nep.common.page;

import java.util.List;

import com.baomidou.mybatisplus.core.metadata.IPage;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public final class PageResult<T> {

    private final List<T> records;
    private final long total;
    private final long pageNum;
    private final long pageSize;

    public static <T> PageResult<T> from(IPage<T> page) {
        return new PageResult<>(page.getRecords(), page.getTotal(), page.getCurrent(), page.getSize());
    }
}
