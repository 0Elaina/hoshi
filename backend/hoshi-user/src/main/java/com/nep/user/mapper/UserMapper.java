package com.nep.user.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.nep.user.entity.User;

@Mapper
public interface UserMapper extends BaseMapper<User> {
    @Select("""
            SELECT id, username, password_hash, nickname, role, status, created_at, updated_at
            FROM users
            WHERE id = #{userId}
            FOR UPDATE
            """)
    User selectByIdForUpdate(@Param("userId") Long userId);
}
